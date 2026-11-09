"""Opt-in, loopback disposable PostgreSQL18 tests using formal T09 migration.

Never use a shared database: T16_ISOLATED_DB_TEST=YES and database name
`t16_profile_test` are both required. No application authentication overrides.
"""
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from sqlalchemy import URL, event, text
from sqlalchemy.orm import Session

from app.core.config import DatabaseSettings, get_settings
from app.core.security import issue_access_token
from app.db import create_db_engine
from app.main import create_app
from app.repositories.profile import PostgresProfileRepository
from tests.conftest import TEST_SECRET, bearer

pytestmark = pytest.mark.skipif(os.environ.get('T16_ISOLATED_DB_TEST') != 'YES',
                                reason='requires disposable loopback PostgreSQL')
ROOT = Path(__file__).resolve().parents[2]
A = UUID('00000000-0000-4000-8000-000000000001')
B = UUID('00000000-0000-4000-8000-000000000002')


@pytest.fixture
def pg_app(monkeypatch):
    if os.environ.get('T16_ISOLATED_DB_TEST') != 'YES':
        pytest.skip('requires disposable PostgreSQL')
    options = conninfo_to_dict(os.environ['T16_TEST_ADMIN_URL'])
    if options.get('host') not in {'127.0.0.1', 'localhost'} or options.get('dbname') != 't16_profile_test':
        pytest.fail('Only loopback disposable t16_profile_test is allowed')
    role = 't16_' + uuid4().hex
    password = secrets.token_urlsafe(24)
    sid = uuid4()
    with psycopg.connect(os.environ['T16_TEST_ADMIN_URL'], autocommit=True) as admin:
        assert 180000 <= admin.info.server_version < 190000
        admin.execute('DROP SCHEMA IF EXISTS career CASCADE')
        admin.execute('CREATE SCHEMA career')
        admin.execute((ROOT/'database/migrations/0001_initial_schema.sql').read_text(encoding='utf-8'))
        admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE').format(
            sql.Identifier(role), sql.Literal(password)))
        admin.execute(sql.SQL('GRANT USAGE ON SCHEMA career TO {}').format(sql.Identifier(role)))
        admin.execute(sql.SQL('GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA career TO {}').format(sql.Identifier(role)))
        for uid, name in [(A,'Synthetic A'), (B,'Synthetic B')]:
            email = name[-1].lower()+'@example.invalid'
            admin.execute('INSERT INTO career.users(user_id,email,email_canonical,display_name) VALUES(%s,%s,%s,%s)',(uid,email,email,name))
            admin.execute('INSERT INTO career.user_profiles(user_id,headline,bio) VALUES(%s,%s,%s)',(uid,'initial','keep'))
        admin.execute('INSERT INTO career.auth_sessions(session_id,user_id,refresh_token_hash,expires_at) VALUES(%s,%s,%s,%s)',
                      (sid,A,'a'*64,datetime.now(UTC)+timedelta(hours=1)))
        url = URL.create('postgresql+psycopg', username=role, password=password, host=options['host'],
                         port=int(options.get('port',5432)), database=options['dbname'])
        runtime = create_db_engine(DatabaseSettings(url=url.render_as_string(hide_password=False),pool_size=3,timeout=5))
        monkeypatch.setenv('APP_ENV','test')
        monkeypatch.setenv('JWT_SECRET',TEST_SECRET)
        monkeypatch.setenv('DATABASE_URL',url.set(drivername='postgresql').render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            with TestClient(create_app(),base_url='https://testserver') as client:
                token = issue_access_token(TEST_SECRET,A,sid,[],3600)
                yield client,runtime,admin,bearer(token)
        finally:
            runtime.dispose()
            get_settings.cache_clear()
            admin.execute('DROP SCHEMA career CASCADE')
            admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))


def test_postgres_roundtrip_and_ownership(pg_app):
    client,engine,admin,headers = pg_app
    assert client.get('/api/v1/me',headers=headers).status_code == 200
    response=client.patch('/api/v1/me',headers=headers,json={'display_name':'Changed','headline':None})
    assert response.status_code==200
    assert response.json()['profile']=={'headline':None,'bio':'keep','location_text':None}
    assert client.get('/api/v1/me',headers=headers).json()==response.json()
    # Independent admin connection proves request COMMIT, not same-session visibility.
    assert admin.execute('SELECT display_name FROM career.users WHERE user_id=%s',(A,)).fetchone()[0]=='Changed'
    assert admin.execute('SELECT display_name FROM career.users WHERE user_id=%s',(B,)).fetchone()[0]=='Synthetic B'
    assert response.headers['cache-control']=='no-store'
    with Session(engine) as db:
        assert db.execute(text('SELECT current_user')).scalar().startswith('t16_')


def test_postgres_atomic_rollback(pg_app):
    client,_,admin,headers=pg_app
    admin.execute("CREATE FUNCTION career.reject_profile() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic private failure'; END $$")
    admin.execute('CREATE TRIGGER reject_profile BEFORE UPDATE ON career.user_profiles FOR EACH ROW EXECUTE FUNCTION career.reject_profile()')
    response=client.patch('/api/v1/me',headers=headers,json={'display_name':'must rollback','bio':'changed'})
    assert response.status_code==503
    assert 'synthetic private failure' not in response.text
    assert admin.execute('SELECT display_name FROM career.users WHERE user_id=%s',(A,)).fetchone()[0]=='Synthetic A'
    assert admin.execute('SELECT bio FROM career.user_profiles WHERE user_id=%s',(A,)).fetchone()[0]=='keep'
    assert client.get('/api/v1/me',headers=headers).status_code==200


def test_postgres_missing_profile_upsert(pg_app):
    client,_,admin,headers=pg_app
    admin.execute('DELETE FROM career.user_profiles WHERE user_id=%s',(A,))
    assert client.get('/api/v1/me',headers=headers).json()['profile']['bio'] is None
    response=client.patch('/api/v1/me',headers=headers,json={'bio':'new profile'})
    assert response.status_code==200 and response.json()['profile']['bio']=='new profile'
    assert admin.execute('SELECT count(*) FROM career.user_profiles WHERE user_id=%s',(A,)).fetchone()[0]==1


def test_postgres_test_writer_is_not_admin(pg_app):
    _,engine,_,_=pg_app
    from sqlalchemy.exc import ProgrammingError
    with Session(engine) as db:
        assert db.execute(text('SELECT rolsuper FROM pg_roles WHERE rolname=current_user')).scalar() is False
        with pytest.raises(ProgrammingError):
            db.execute(text('DELETE FROM career.users WHERE user_id=:uid'),{'uid':B})
        db.rollback()


def test_postgres_invalid_and_disabled(pg_app):
    client,_,admin,headers=pg_app
    assert client.patch('/api/v1/me',headers=headers,json={'email':'forbidden@example.invalid'}).status_code==422
    admin.execute("UPDATE career.users SET status='disabled' WHERE user_id=%s",(A,))
    # T15 denies disabled principals before the profile endpoint.
    assert client.get('/api/v1/me',headers=headers).status_code==401
    assert client.patch('/api/v1/me',headers=headers,json={'headline':'no'}).status_code==401


def test_postgres_real_auth_rejects_invalid_revoked_and_foreign_tokens(pg_app):
    client,_,admin,headers=pg_app
    for h in [{},bearer('unsigned.synthetic.token'),bearer(issue_access_token(TEST_SECRET,B,uuid4(),[],3600))]:
        for method in ['get','patch']:
            response=getattr(client,method)('/api/v1/me',headers=h,**({'json':{'bio':'no'}} if method=='patch' else {}))
            assert response.status_code==401 and response.headers['cache-control']=='no-store'
    for method in ['get','patch']:
        assert getattr(client,method)('/api/v1/me?user_id='+str(B),headers=headers,**({'json':{'bio':'no'}} if method=='patch' else {})).status_code==422
    admin.execute('UPDATE career.auth_sessions SET revoked_at=now()')
    assert client.patch('/api/v1/me',headers=headers,json={'bio':'no'}).status_code==401


def test_postgres_concurrent_patches_preserve_omitted_fields(pg_app):
    _,engine,admin,_=pg_app
    def patch(changes):
        with Session(engine) as db:
            # Simulate the read transaction opened by T15 authentication.
            db.execute(text('SELECT user_id FROM career.users WHERE user_id=:uid'),{'uid':A}).one()
            return PostgresProfileRepository(db).patch(A,changes)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(patch,[{'headline':'concurrent headline'},{'bio':'concurrent bio'}]))
    assert all(r.user_id==A for r in results)
    assert admin.execute('SELECT headline,bio FROM career.user_profiles WHERE user_id=%s',(A,)).fetchone()==('concurrent headline','concurrent bio')
    assert engine.pool.checkedout()==0


def test_postgres_commit_failure_rolls_back_and_returns_connection(pg_app):
    _,engine,admin,_=pg_app
    from sqlalchemy.exc import OperationalError
    def fail_commit(_):
        raise OperationalError(None,None,RuntimeError('synthetic commit failure'))
    with Session(engine) as db:
        event.listen(db,'before_commit',fail_commit)
        from app.core.errors import AppError
        with pytest.raises(AppError) as exc:
            PostgresProfileRepository(db).patch(A,{'display_name':'must rollback'})
        assert exc.value.status==503
        assert not db.in_transaction()
    assert engine.pool.checkedout()==0
    assert admin.execute('SELECT display_name FROM career.users WHERE user_id=%s',(A,)).fetchone()[0]=='Synthetic A'


def test_integrated_staging_entrypoint_reuses_real_t14_t15_t16(pg_app, monkeypatch):
    import importlib.util
    _, _, admin, headers = pg_app
    monkeypatch.setenv('ENABLE_SERVICE_API', '1')
    monkeypatch.setenv('ENABLE_CRAWLER_API', '1')
    monkeypatch.syspath_prepend(str(ROOT))
    spec = importlib.util.spec_from_file_location('staging_t16_pg', ROOT/'poc/staging/backend/main.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with TestClient(module.app, base_url='https://testserver') as client:
        assert client.get('/api/v1/me').status_code == 401
        assert client.get('/api/v1/me', headers=headers).status_code == 200
        response = client.patch('/api/v1/me', headers=headers, json={'headline':'staging entrypoint'})
        assert response.status_code == 200
        assert response.json()['profile']['bio'] == 'keep'
        assert admin.execute('SELECT headline FROM career.user_profiles WHERE user_id=%s',(A,)).fetchone()[0] == 'staging entrypoint'
        assert client.get('/api/v1/me', headers=headers).json() == response.json()
        assert admin.execute('SELECT headline FROM career.user_profiles WHERE user_id=%s',(B,)).fetchone()[0] == 'initial'
        spec = client.get('/openapi.json').json()
        assert 'patch' in spec['paths']['/api/v1/me']
        assert '/api/jobs/collected' in spec['paths']
