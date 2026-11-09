"""T31 actual PostgreSQL tests, reusing the guarded T16 disposable DB fixture."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.repositories.privacy import SqlPrivacyRepository
from app.schemas.privacy import OptionalConsentInput
from app.services.privacy import PrivacyService
from tests.test_profile_postgres import pg_app, A, B, ROOT

MIGRATION = ROOT/'database/migrations/0002_deletion_request_unscheduled.sql'

@pytest.fixture
def privacy_pg(pg_app):
    client,engine,admin,headers=pg_app
    admin.execute(MIGRATION.read_text(encoding='utf-8'))
    now=datetime.now(UTC)
    for code,version,required,effective in [
        ('terms','v1',True,now-timedelta(days=1)),
        ('llm_processing','v0',False,now-timedelta(days=2)),
        ('llm_processing','v1',False,now-timedelta(days=1)),
        ('llm_processing','future',False,now+timedelta(days=1)),
    ]:
        admin.execute('INSERT INTO career.consent_policies(policy_code,version,is_required,content_url,effective_at) VALUES(%s,%s,%s,%s,%s)',(code,version,required,'https://example.invalid/qa',effective))
    return client,engine,admin,headers


def body(granted=False,version='v1',code='llm_processing'):
    return {'policy_code':code,'policy_version':version,'granted':granted}


def test_actual_consent_append_history_idempotency_and_owner(privacy_pg):
    client,_,admin,h=privacy_pg
    admin.execute("INSERT INTO career.user_consents(user_id,policy_code,policy_version,granted) VALUES(%s,'llm_processing','v1',true)",(B,))
    assert client.get('/api/v1/me/consents',headers=h).json()==[]
    r=client.post('/api/v1/me/consents',headers=h,json=body())
    assert r.status_code==201
    row=r.json();assert row['granted'] is False and row['is_required'] is False
    assert client.post('/api/v1/me/consents',headers=h,json=body()).json()['consent_id']==row['consent_id']
    grant=client.post('/api/v1/me/consents',headers=h,json=body(True));assert grant.status_code==201
    revoke=client.post('/api/v1/me/consents',headers=h,json=body(False));assert revoke.status_code==201
    history=client.get('/api/v1/me/consents',headers=h).json()
    assert len(history)==3 and [x['granted'] for x in history]==[False,True,False]
    assert admin.execute('SELECT count(*) FROM career.user_consents WHERE user_id=%s',(A,)).fetchone()[0]==3
    assert admin.execute('SELECT count(*) FROM career.user_consents WHERE user_id=%s',(B,)).fetchone()[0]==1


@pytest.mark.parametrize('payload',[body(version='v0'),body(version='future'),body(code='behavior_tracking'),body(code='terms')])
def test_actual_policy_must_be_latest_effective_optional(privacy_pg,payload):
    client,_,admin,h=privacy_pg
    assert client.post('/api/v1/me/consents',headers=h,json=payload).status_code==422
    assert admin.execute('SELECT count(*) FROM career.user_consents WHERE user_id=%s',(A,)).fetchone()[0]==0


def test_actual_optional_code_marked_required_is_rejected(privacy_pg):
    client,_,admin,h=privacy_pg
    admin.execute("UPDATE career.consent_policies SET is_required=true WHERE policy_code='llm_processing' AND version='v1'")
    assert client.post('/api/v1/me/consents',headers=h,json=body()).status_code==422


def test_actual_deletion_intake_is_atomic_and_auth_fails_closed(privacy_pg):
    client,_,admin,h=privacy_pg
    assert client.get('/api/v1/me/deletion-request',headers=h).status_code==404
    r=client.post('/api/v1/me/deletion-request',headers=h,json={'confirmation':'DELETE'})
    assert r.status_code==202 and r.headers['location']=='/api/v1/me/deletion-request'
    assert r.json()['scheduled_purge_at'] is None and r.json()['status']=='requested'
    assert admin.execute('SELECT status FROM career.users WHERE user_id=%s',(A,)).fetchone()[0]=='disabled'
    assert admin.execute('SELECT count(*) FROM career.auth_sessions WHERE user_id=%s AND revoked_at IS NULL',(A,)).fetchone()[0]==0
    assert admin.execute("SELECT count(*) FROM career.account_deletion_requests WHERE user_id=%s AND status='requested'",(A,)).fetchone()[0]==1
    assert admin.execute('SELECT status FROM career.users WHERE user_id=%s',(B,)).fetchone()[0]=='active'
    assert client.get('/api/v1/me',headers=h).status_code==401
    # Known contract gap: disabled users cannot poll/cancel with revoked JWT.
    assert client.delete('/api/v1/me/deletion-request',headers=h).status_code==401


def test_actual_pending_request_get_duplicate_and_cancel_hold(privacy_pg):
    client,_,admin,h=privacy_pg
    # Historical/operator-prepared pending request on an active synthetic account.
    admin.execute('INSERT INTO career.account_deletion_requests(user_id,scheduled_purge_at) VALUES(%s,NULL)',(A,))
    assert client.get('/api/v1/me/deletion-request',headers=h).status_code==200
    r=client.post('/api/v1/me/deletion-request',headers=h,json={'confirmation':'DELETE'})
    assert r.status_code==409 and r.json()['code']=='DELETION_ALREADY_REQUESTED'
    assert client.delete('/api/v1/me/deletion-request',headers=h).status_code==503
    assert admin.execute('SELECT status FROM career.users WHERE user_id=%s',(A,)).fetchone()[0]=='active'
    assert admin.execute('SELECT status FROM career.account_deletion_requests WHERE user_id=%s',(A,)).fetchone()[0]=='requested'
    assert client.get('/api/v1/me/deletion-request?user_id='+str(B),headers=h).status_code==422


def test_actual_consent_commit_error_rolls_back(privacy_pg):
    _,engine,admin,_=privacy_pg
    observed=[]
    with Session(engine) as db:
        def fail_commit(session):
            observed.append(session.execute(text('SELECT count(*) FROM career.user_consents WHERE user_id=:uid'),{'uid':A}).scalar_one())
            raise OperationalError(None,None,RuntimeError('synthetic commit failure'))
        event.listen(db,'before_commit',fail_commit)
        with pytest.raises(AppError) as exc:
            PrivacyService(SqlPrivacyRepository(db)).record_consent(A,OptionalConsentInput(**body()))
        assert exc.value.status==503 and not db.in_transaction()
    assert observed==[1] and engine.pool.checkedout()==0
    assert admin.execute('SELECT count(*) FROM career.user_consents WHERE user_id=%s',(A,)).fetchone()[0]==0


def test_actual_deletion_final_revoke_error_rolls_back_every_change(privacy_pg):
    _,engine,admin,_=privacy_pg
    observed=[]
    def fail_revoke(connection,cursor,statement,parameters,context,executemany):
        if statement.startswith('UPDATE career.auth_sessions'):
            pending=connection.execute(text('SELECT count(*) FROM career.account_deletion_requests WHERE user_id=:uid'),{'uid':A}).scalar_one()
            status=connection.execute(text('SELECT status FROM career.users WHERE user_id=:uid'),{'uid':A}).scalar_one()
            observed.append((pending,status))
            raise IntegrityError(None,None,RuntimeError('synthetic revoke failure'))
    event.listen(engine,'before_cursor_execute',fail_revoke)
    try:
        with Session(engine) as db:
            with pytest.raises(AppError) as exc:PrivacyService(SqlPrivacyRepository(db)).request_deletion(A)
            assert exc.value.status==503 and not db.in_transaction()
    finally:event.remove(engine,'before_cursor_execute',fail_revoke)
    assert observed==[(1,'disabled')] and engine.pool.checkedout()==0
    assert admin.execute('SELECT count(*) FROM career.account_deletion_requests WHERE user_id=%s',(A,)).fetchone()[0]==0
    assert admin.execute('SELECT status FROM career.users WHERE user_id=%s',(A,)).fetchone()[0]=='active'
    assert admin.execute('SELECT count(*) FROM career.auth_sessions WHERE user_id=%s AND revoked_at IS NULL',(A,)).fetchone()[0]==1


def test_actual_concurrent_consent_is_not_duplicated(privacy_pg):
    _,engine,admin,_=privacy_pg
    start=Barrier(2)
    def record(_):
        with Session(engine) as db:
            start.wait(timeout=5)
            return PrivacyService(SqlPrivacyRepository(db)).record_consent(A,OptionalConsentInput(**body())).consent_id
    with ThreadPoolExecutor(max_workers=2) as pool:ids=list(pool.map(record,range(2)))
    assert ids[0]==ids[1]
    assert admin.execute('SELECT count(*) FROM career.user_consents WHERE user_id=%s',(A,)).fetchone()[0]==1


def test_actual_concurrent_deletion_has_one_pending_request(privacy_pg):
    _,engine,admin,_=privacy_pg
    start=Barrier(2)
    def create(_):
        with Session(engine) as db:
            start.wait(timeout=5)
            try:return PrivacyService(SqlPrivacyRepository(db)).request_deletion(A).status
            except AppError as exc:return exc.status
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(create,range(2)))
    assert results.count('requested')==1 and results.count(409)==1
    assert admin.execute('SELECT count(*) FROM career.account_deletion_requests WHERE user_id=%s',(A,)).fetchone()[0]==1


def test_actual_minimal_migration_rollback_and_repeat(pg_app):
    _,_,admin,_=pg_app
    q="SELECT is_nullable FROM information_schema.columns WHERE table_schema='career' AND table_name='account_deletion_requests' AND column_name='scheduled_purge_at'"
    assert admin.execute(q).fetchone()[0]=='NO'
    class Abort(Exception):pass
    try:
        with admin.transaction():
            admin.execute(MIGRATION.read_text(encoding='utf-8'))
            assert admin.execute(q).fetchone()[0]=='YES'
            raise Abort()
    except Abort:pass
    assert admin.execute(q).fetchone()[0]=='NO'
    for _ in range(2):admin.execute(MIGRATION.read_text(encoding='utf-8'))
    assert admin.execute(q).fetchone()[0]=='YES'
    assert admin.execute('SELECT count(*) FROM career.account_deletion_requests').fetchone()[0]==0
