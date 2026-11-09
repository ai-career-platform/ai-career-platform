"""Real Docker/Nginx HTTP smoke test; only creates uniquely named disposable containers.

Run after building crawler-staging-test and crawler-staging-frontend-test.
No DB/volume, migrations, collection, or existing container changes.
"""
import json
import subprocess
import time
import urllib.error
import urllib.request
from uuid import uuid4


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


def main():
    suffix = uuid4().hex[:12]
    network = 't16-smoke-' + suffix
    backend, frontend = network + '-backend', network + '-frontend'
    docker('network', 'create', network)
    try:
        docker('run', '-d', '--name', backend, '--network', network, '--network-alias', 'backend',
               '-e', 'APP_ENV=test', '-e', 'JWT_SECRET=synthetic-docker-smoke-only-0123456789',
               '-e', 'CRAWLER_DB_MODE=staging', 'crawler-staging-test')
        docker('run', '-d', '--name', frontend, '--network', network, '-p', '127.0.0.1::80',
               'crawler-staging-frontend-test')
        docker('exec', frontend, 'nginx', '-t')
        port = docker('port', frontend, '80/tcp').split(':')[-1]
        base = 'http://127.0.0.1:' + port

        def request(path, method='GET', headers=None, body=None):
            req = urllib.request.Request(base + path, method=method, headers=headers or {}, data=body)
            try:
                with urllib.request.urlopen(req, timeout=3) as response:
                    return response.status, response.read(), response.headers
            except urllib.error.HTTPError as error:
                return error.code, error.read(), error.headers

        for _ in range(30):
            try:
                if request('/api/health')[0] == 200:
                    break
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(0.5)
        else:
            raise AssertionError('Integrated image did not become healthy')
        assert request('/api/version')[0] == 200
        assert request('/api/health/db')[0] == 503  # no test DB supplied
        assert request('/api/jobs/collected')[0] == 503  # route present, DB intentionally absent
        spec = json.loads(request('/api/openapi.json')[1])
        assert {'get', 'patch'} <= set(spec['paths']['/api/v1/me'])
        assert '/api/jobs/collected' in spec['paths']
        assert spec['servers'] == [{'url': '/'}]
        assert b'/api/openapi.json' in request('/api/docs')[1]
        for method in ['GET', 'PATCH']:
            status, body, headers = request('/api/v1/me', method,
                {'Content-Type': 'application/json'}, b'{"bio":"synthetic"}' if method=='PATCH' else None)
            assert status == 401 and json.loads(body)['code'] == 'UNAUTHENTICATED'
            assert headers['Cache-Control'] == 'no-store'
        # A valid signed token reaches DB readiness (503), proving Nginx forwarded Authorization.
        from datetime import UTC, datetime, timedelta
        import jwt
        now = datetime.now(UTC)
        token = jwt.encode({'iss':'ai-career-platform','sub':str(uuid4()),'sid':str(uuid4()),
                            'typ':'access','iat':now,'exp':now+timedelta(minutes=1)},
                           'synthetic-docker-smoke-only-0123456789',algorithm='HS256')
        status, body, _ = request('/api/v1/me', headers={'Authorization':'Bearer '+token})
        assert status == 503 and json.loads(body)['code'] == 'DEPENDENCY_UNAVAILABLE'
        print('DOCKER_BUILD_NGINX_AND_T16_ROUTES=PASS')
    finally:
        for name in [frontend, backend]:
            subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        docker('network', 'rm', network)


if __name__ == '__main__':
    main()
