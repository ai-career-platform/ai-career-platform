"""T31 route/DTO unit checks; repositories are mocked, not DB evidence."""
from unittest.mock import Mock
from uuid import uuid4

import pytest
from app.core.errors import AppError, ErrorCode
from app.routers.privacy import get_privacy_service
from tests.conftest import signup, bearer

PATH = '/api/v1/me'

@pytest.fixture
def privacy_client(app, client):
    token = signup(client).json()['access_token']
    service = Mock()
    app.dependency_overrides[get_privacy_service] = lambda: service
    return client, bearer(token), service

@pytest.mark.parametrize('method,path,body', [
    ('get','/consents',None),('post','/consents',{'policy_code':'llm_processing','policy_version':'v1','granted':False}),
    ('get','/deletion-request',None),('post','/deletion-request',{'confirmation':'DELETE'}),
    ('delete','/deletion-request',None),
])
def test_unauthenticated_privacy_is_401(client,method,path,body):
    r=getattr(client,method)(PATH+path,**({'json':body} if body is not None else {}))
    assert r.status_code==401
    assert r.headers['cache-control']=='no-store'

@pytest.mark.parametrize('body', [
    {'policy_code':'terms','policy_version':'v1','granted':True},
    {'policy_code':'privacy','policy_version':'v1','granted':False},
    {'policy_code':'llm_processing','policy_version':'','granted':False},
    {'policy_code':'llm_processing','policy_version':'v1','granted':'false'},
    {'policy_code':'llm_processing','policy_version':'v1','granted':False,'user_id':str(uuid4())},
])
def test_invalid_optional_consent_is_rejected(privacy_client,body):
    client,h,service=privacy_client
    assert client.post(PATH+'/consents',headers=h,json=body).status_code==422
    service.record_consent.assert_not_called()

@pytest.mark.parametrize('body',[{}, {'confirmation':'delete'}, {'confirmation':'DELETE','user_id':str(uuid4())}])
def test_invalid_deletion_confirmation_is_rejected(privacy_client,body):
    client,h,service=privacy_client
    assert client.post(PATH+'/deletion-request',headers=h,json=body).status_code==422
    service.request_deletion.assert_not_called()

def test_current_user_query_is_not_accepted(privacy_client):
    client,h,service=privacy_client
    assert client.get(PATH+'/consents?user_id='+str(uuid4()),headers=h).status_code==422
    service.list_consents.assert_not_called()

def test_existing_error_contract_and_safe_cancel_hold(privacy_client):
    client,h,service=privacy_client
    service.get_deletion.side_effect=AppError(ErrorCode.NOT_FOUND)
    assert client.get(PATH+'/deletion-request',headers=h).status_code==404
    service.cancel_deletion.side_effect=AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
    r=client.delete(PATH+'/deletion-request',headers=h)
    assert r.status_code==503 and set(r.json())=={'code','status','message'}
    assert r.headers['cache-control']=='no-store'

def test_privacy_swagger_declares_five_operations(client):
    spec=client.get('/openapi.json').json()
    assert set(spec['paths'][PATH+'/consents'])=={'get','post'}
    assert set(spec['paths'][PATH+'/deletion-request'])=={'get','post','delete'}
    assert spec['paths'][PATH+'/deletion-request']['delete']['x-implementation-status']=='HOLD'

    import yaml
    from pathlib import Path
    contract = yaml.safe_load((Path(__file__).parents[2]/'docs/api/openapi.yaml').read_text(encoding='utf-8'))
    purge = contract['components']['schemas']['DeletionRequest']['properties']['scheduled_purge_at']
    assert 'null' in purge.get('type', [])
