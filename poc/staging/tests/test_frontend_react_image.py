"""F-02 static guards for the Staging frontend image (React app + PoC status page).

The real container behaviour is checked by docker_route_smoke.py in CI; these tests keep the
configuration contract cheap to verify: API proxy blocks unchanged, security headers on every
static location, SPA fallback that cannot swallow /api, and no Mock/unapproved UI flag enabled.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FRONTEND = ROOT / 'poc' / 'staging' / 'frontend'
NGINX = (FRONTEND / 'nginx.conf').read_text(encoding='utf-8')
DOCKERFILE = (FRONTEND / 'Dockerfile.integrated').read_text(encoding='utf-8')
SECURITY_HEADERS = ['X-Content-Type-Options "nosniff"', 'X-Frame-Options "DENY"',
                    'Referrer-Policy "strict-origin-when-cross-origin"', "Content-Security-Policy \"default-src 'none'"]


def blocks():
    found = {}
    for match in re.finditer(r'location\s+(=\s+)?(\S+)\s*\{(.*?)\n    \}', NGINX, re.S):
        found[(match.group(1) or '') + match.group(2)] = match.group(3)
    return found


def test_api_proxy_blocks_unchanged():
    b = blocks()
    assert 'proxy_pass http://backend:8000;' in b['/api/v1/']
    assert 'proxy_set_header Authorization $http_authorization;' in b['/api/v1/']
    assert 'proxy_pass http://backend:8000/;' in b['/api/']
    assert 'try_files' not in b['/api/v1/'] + b['/api/']


def test_static_locations_keep_security_headers_and_spa_rules():
    b = blocks()
    for name in ['/', '= /index.html', '/assets/']:
        for header in SECURITY_HEADERS:
            assert header in b[name], (name, header)
    assert 'try_files $uri /index.html;' in b['/']
    assert 'try_files $uri =404;' in b['/assets/'] and 'immutable' in b['/assets/']
    assert 'no-cache' in b['= /index.html']
    assert "script-src 'self'" in b['/'] and 'unsafe-inline' not in NGINX


def test_image_keeps_status_page_and_disables_mock_and_unapproved_flags():
    assert 'COPY index.html /usr/share/nginx/html/staging-status.html' in DOCKERFILE
    assert 'COPY status.js status.css /usr/share/nginx/html/' in DOCKERFILE
    assert 'VITE_API_BASE_URL=/api' in DOCKERFILE and 'VITE_API_MOCK=false' in DOCKERFILE
    assert not re.search(r'VITE_[A-Z_]+=true', DOCKERFILE)
    # Tests run with the default base '/'; only the build is placed under /career/ (shared origin, Redmine at /).
    assert 'npm run lint && npm test && VITE_BASE_PATH=/career/ VITE_API_BASE_URL=/career/api npm run build' in DOCKERFILE
    assert 'COPY --from=docs . /repo/docs' in DOCKERFILE  # contract tests read ../docs; none may be skipped
    # Every VITE_* flag read by the app is either pinned off here or only effective with VITE_API_MOCK=true.
    env_ts = (ROOT / 'frontend' / 'src' / 'config' / 'env.ts').read_text(encoding='utf-8')
    # Flags that work without mock mode (`key: import.meta.env.VITE_X === 'true',`). Only approved ones may exist,
    # and each must be pinned off in the image. #346/#347/#348 moved three UIs from mock-only to real API (default off).
    standalone = set(re.findall(r"^\s*\w+: import\.meta\.env\.(VITE_\w+) === 'true',", env_ts, re.M)) - {'VITE_API_MOCK'}
    allowed = {'VITE_CRAWLER_ADMIN_UI', 'VITE_SKILL_AUTOCOMPLETE', 'VITE_BEHAVIOR_TRACKING',
               'VITE_APPLICATIONS_UI', 'VITE_ADMIN_AUDIT_UI', 'VITE_JOB_SEARCH_ADVANCED_UI'}
    assert {'VITE_CRAWLER_ADMIN_UI', 'VITE_SKILL_AUTOCOMPLETE', 'VITE_BEHAVIOR_TRACKING'} <= standalone <= allowed, standalone
    for flag in allowed:
        assert f'{flag}=false' in DOCKERFILE, flag
    flags = set(re.findall(r'import\.meta\.env\.(VITE_\w+)', env_ts))
    mock_gated = {f for f in flags if re.search(rf"VITE_API_MOCK === 'true' &&[^,]*{f}", env_ts, re.S)}
    assert flags - mock_gated - standalone == {'VITE_API_BASE_URL', 'VITE_API_MOCK'}


def test_career_prefixed_assets_are_served_but_never_fall_back_to_the_shell():
    b = blocks()
    assert 'alias /usr/share/nginx/html/assets/;' in b['/career/assets/']
    assert 'try_files' not in b['/career/assets/'] and 'immutable' in b['/career/assets/']
    for header in SECURITY_HEADERS:
        assert header in b['/career/assets/'], header


def test_publish_and_ci_build_the_integrated_image():
    publish = (ROOT / '.github' / 'workflows' / 'staging-publish.yml').read_text(encoding='utf-8')
    assert 'file: ./poc/staging/frontend/Dockerfile.integrated' in publish
    assert 'app=./frontend' in publish and 'docs=./docs' in publish
    crawler_ci = (ROOT / '.github' / 'workflows' / 'crawler-mvp.yml').read_text(encoding='utf-8')
    assert '--build-context app=frontend --build-context docs=docs -f poc/staging/frontend/Dockerfile.integrated' in crawler_ci
    # Server-side files are intentionally untouched by F-02 (protected compose hash, deploy logic).
    assert (FRONTEND / 'Dockerfile').read_text(encoding='utf-8').startswith('FROM nginx:1.27.5-alpine')
