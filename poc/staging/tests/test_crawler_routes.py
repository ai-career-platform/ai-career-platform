import importlib.util
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient


def load(monkeypatch):
    monkeypatch.setenv('ENABLE_CRAWLER_API', '1')
    path = Path(__file__).resolve().parents[1] / 'backend/main.py'
    spec = importlib.util.spec_from_file_location('integrated_staging', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_staging_includes_crawler_without_replacing_health(monkeypatch):
    module = load(monkeypatch)
    client = TestClient(module.app)
    with patch('backend.training_jobs_api.read_collected_jobs', return_value=[]):
        assert client.get('/jobs/collected').status_code == 200
    assert client.get('/health').status_code == 200
    assert client.get('/training').status_code == 200
    assert '/jobs/collected' in client.get('/openapi.json').json()['paths']


def test_staging_crawler_missing_configuration_is_sanitized(monkeypatch):
    module = load(monkeypatch)
    monkeypatch.setenv('CRAWLER_DB_MODE', 'staging')
    monkeypatch.delenv('CRAWLER_STAGING_DATABASE_URL', raising=False)
    response = TestClient(module.app).get('/jobs/collected')
    assert response.status_code == 503
    assert response.json() == {'detail': 'Training database unavailable'}


def test_integrated_service_profile_and_swagger_contract(monkeypatch):
    monkeypatch.setenv('ENABLE_SERVICE_API', '1')
    monkeypatch.setenv('APP_ENV', 'test')
    monkeypatch.delenv('DATABASE_URL', raising=False)
    module = load(monkeypatch)
    with TestClient(module.app) as client:
        spec = client.get('/openapi.json').json()
        assert {'get','patch'} <= set(spec['paths']['/api/v1/me'])
        assert '/api/jobs/collected' in spec['paths']
        assert spec.get('servers', [{'url':'/'}])[0]['url'] == '/'
        assert '/api/openapi.json' in client.get('/docs').text
        response = client.get('/api/v1/me')
        assert response.status_code == 401
        assert response.json()['code'] == 'UNAUTHENTICATED'
        assert response.headers['cache-control'] == 'no-store'
        assert client.patch('/api/v1/me', json={'bio':'synthetic'}).status_code == 401
        assert client.get('/health').status_code == 200
        with patch('backend.training_jobs_api.read_collected_jobs', return_value=[]):
            assert client.get('/jobs/collected').status_code == 200
