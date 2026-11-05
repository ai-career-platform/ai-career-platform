#!/usr/bin/env python3
"""Outbound-only, fail-closed Staging deployer. Never executes downloaded code."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import io
import json
import os
import platform
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile

REPO = 'ai-career-platform/ai-career-platform'
PROJECT = 'ai-career-staging-poc'
ROOT = Path('/home/kant/ai-career-staging-poc')
WORKFLOW = '.github/workflows/staging-publish.yml'
CI_WORKFLOW = '.github/workflows/ci.yml'
ARTIFACT = 'verified-staging-release'
SERVICES = ('frontend', 'backend')


class Hold(Exception):
    """Only constant, non-secret reason codes belong in this exception."""


def require(condition, reason):
    if not condition:
        raise Hold(reason)


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def sync_directory(path):
    if os.name == 'posix':
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic_json(path, value):
    require(not path.is_symlink(), 'STATE_SYMLINK')
    tmp = path.with_suffix('.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(value, out, sort_keys=True)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
        sync_directory(path.parent)
    except BaseException:
        # A crash may leave the private temp file; operator review is required.
        raise


@contextmanager
def lock_file(path):
    import fcntl  # Linux-only; offline tests replace this boundary.
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        require(urllib.parse.urlsplit(newurl).scheme == 'https', 'INSECURE_REDIRECT')
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if urllib.parse.urlsplit(newurl).netloc != 'api.github.com':
            redirected.remove_header('Authorization')
        return redirected


class GitHub:
    def __init__(self, token):
        require(bool(token.strip()), 'MISSING_GITHUB_CREDENTIAL')
        self.token = token.strip()
        self.opener = urllib.request.build_opener(SafeRedirect())

    def request(self, path, raw=False):
        require(path.startswith('/repos/' + REPO + '/'), 'INVALID_API_PATH')
        req = urllib.request.Request('https://api.github.com' + path, headers={
            'Authorization': 'Bearer ' + self.token,
            'Accept': 'application/vnd.github+json', 'User-Agent': PROJECT})
        with self.opener.open(req, timeout=15) as response:
            data = response.read(5_000_001)
        require(len(data) <= 5_000_000, 'API_RESPONSE_TOO_LARGE')
        return data if raw else json.loads(data)

    def run(self, run_id):
        require(type(run_id) is int and run_id > 0, 'INVALID_RUN_ID')
        return self.request(f'/repos/{REPO}/actions/runs/{run_id}')

    def ci_jobs(self, run_id):
        result = self.request(f'/repos/{REPO}/actions/runs/{run_id}/jobs?per_page=100&filter=latest')
        require(result['total_count'] <= 100, 'JOB_PAGINATION_REQUIRED')
        return result['jobs']

    def merged_pulls(self, sha):
        pulls = self.request(f'/repos/{REPO}/commits/{sha}/pulls?per_page=100')
        require(len(pulls) < 100, 'PULL_PAGINATION_REQUIRED')
        # List responses need not include merged_by; retrieve the full PR object.
        return [self.request(f'/repos/{REPO}/pulls/{p["number"]}') for p in pulls if p.get('merged_at')]

    def is_forward(self, old, new):
        require(re.fullmatch('[0-9a-f]{40}', old) is not None, 'INVALID_PREVIOUS_SHA')
        result = self.request(f'/repos/{REPO}/compare/{old}...{new}')
        return result['status'] == 'ahead' and result['merge_base_commit']['sha'] == old

    def candidate(self):
        # Select latest run, not latest successful run: a newer failed/pending publication blocks.
        listing = self.request(f'/repos/{REPO}/actions/workflows/staging-publish.yml/runs?branch=main&event=workflow_run&per_page=1')
        require(bool(listing['workflow_runs']), 'NO_PUBLISHED_RELEASE')
        run = self.run(listing['workflow_runs'][0]['id'])
        require(run['status'] == 'completed' and run['conclusion'] == 'success', 'PUBLISH_NOT_SUCCESS')
        result = self.request(f'/repos/{REPO}/actions/runs/{run["id"]}/artifacts?per_page=100')
        require(result['total_count'] <= 100, 'ARTIFACT_PAGINATION_REQUIRED')
        artifacts = [a for a in result['artifacts'] if a['name'] == ARTIFACT and not a['expired']]
        require(len(artifacts) == 1, 'MISSING_OR_AMBIGUOUS_ARTIFACT')
        artifact = artifacts[0]
        require(artifact['workflow_run']['id'] == run['id'], 'ARTIFACT_RUN_MISMATCH')
        archive = self.request(f'/repos/{REPO}/actions/artifacts/{artifact["id"]}/zip', raw=True)
        require('sha256:' + hashlib.sha256(archive).hexdigest() == artifact.get('digest'), 'ARTIFACT_DIGEST_MISMATCH')
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            require(z.namelist() == ['release.json'], 'UNEXPECTED_ARTIFACT_CONTENT')
            require(z.getinfo('release.json').file_size <= 16384, 'MANIFEST_TOO_LARGE')
            manifest = json.loads(z.read('release.json'))
        return manifest, run


def validate_release(api, release, publisher, previous, approvers):
    require(bool(approvers), 'APPROVER_MAPPING_REQUIRED')
    require(release['schema'] == 1 and release['repository'] == REPO, 'REPOSITORY_MISMATCH')
    require(release['branch'] == 'main', 'BRANCH_MISMATCH')
    sha = release['sha']
    require(isinstance(sha, str) and re.fullmatch('[0-9a-f]{40}', sha), 'INVALID_SHA')
    require(set(release['images']) == set(SERVICES), 'INVALID_SERVICE_SET')
    for service in SERVICES:
        expected = f'ghcr.io/ai-career-platform/ai-career-platform-{service}@sha256:[0-9a-f]{{64}}'
        require(re.fullmatch(expected, release['images'][service]) is not None, 'INVALID_IMAGE_DIGEST')
    require(release['publish_run_id'] == publisher['id'] and release['run_number'] == publisher['run_number'], 'PUBLISH_ID_MISMATCH')
    for run, event, path in [(publisher, 'workflow_run', WORKFLOW),
                              (api.run(release['ci_run_id']), 'push', CI_WORKFLOW)]:
        require(run['repository']['full_name'] == REPO and run['head_branch'] == 'main', 'RUN_SOURCE_MISMATCH')
        require(run['event'] == event and run['path'] == path, 'WORKFLOW_MISMATCH')
        require(run['head_sha'] == sha, 'RUN_SHA_MISMATCH')
        require(run['status'] == 'completed' and run['conclusion'] == 'success', 'CI_OR_PUBLISH_NOT_SUCCESS')
    jobs = api.ci_jobs(release['ci_run_id'])
    required = [j for j in jobs if j['name'] == 'CI Smoke Test']
    require(len(required) == 1 and required[0]['status'] == 'completed' and required[0]['conclusion'] == 'success', 'REQUIRED_CI_JOB_NOT_SUCCESS')
    pulls = api.merged_pulls(sha)
    require(any(p.get('merged_at') and p.get('merge_commit_sha') == sha
                and p['base']['ref'] == 'main' and p['base']['repo']['full_name'] == REPO
                and (p.get('merged_by') or {}).get('login', '').lower() in approvers
                for p in pulls), 'AUTHORIZED_MERGE_NOT_PROVEN')
    if previous:
        if previous['sha'] == sha:
            require(previous['images'] == release['images'], 'SAME_SHA_DIFFERENT_DIGEST')
            return 'UNCHANGED'
        require(release['run_number'] > previous['run_number'], 'REPLAYED_PUBLICATION')
        require(api.is_forward(previous['sha'], sha), 'NON_FORWARD_DEPLOYMENT')
        require(previous['images'] != release['images'], 'NEW_SHA_WITH_UNCHANGED_IMAGES')
    return 'APPROVED'


def command(args, env=None):
    try:
        result = subprocess.run(args, check=True, capture_output=True, text=True,
                                timeout=300, env=env)
        return result.stdout
    except (subprocess.SubprocessError, OSError):
        # Docker output may contain environment/registry details. Do not log it.
        raise Hold('DOCKER_COMMAND_FAILED') from None


def check_health(sha):
    # Six rounds, four requests/round, 3s timeout/request, 5s between rounds: <=97s.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(6):
        try:
            for path in ('/', '/api/health', '/api/version', '/api/health/db'):
                with opener.open('http://127.0.0.1:18080' + path, timeout=3) as r:
                    require(r.status == 200 and r.url == 'http://127.0.0.1:18080' + path, 'HEALTH_HTTP_FAILURE')
                    data = r.read(65537)
                    require(len(data) <= 65536, 'HEALTH_RESPONSE_TOO_LARGE')
                if path == '/api/version':
                    require(json.loads(data)['version'] == sha, 'VERSION_NOT_UPDATED')
            return
        except Exception:
            if attempt < 5: time.sleep(5)
    raise Hold('HEALTH_CHECK_FAILED')


def service_rows(runner, compose, env):
    output = runner(compose + ['ps', '--format', 'json', '--all'], env=env).strip()
    return json.loads(output) if output.startswith('[') else [json.loads(s) for s in output.splitlines()]


def execute(api, root, approvers, runner=command, health=check_health, locker=lock_file):
    state_dir = root / '.deploy-state'
    require(not state_dir.is_symlink(), 'STATE_DIRECTORY_SYMLINK')
    state_dir.mkdir(mode=0o700, exist_ok=True)
    with locker(state_dir / 'deploy.lock') as acquired:
        if not acquired:
            print(json.dumps(dict(at=utcnow(), status='LOCKED')))
            return 'LOCKED'
        release = None
        previous = None
        if (state_dir / 'hold.json').exists() or (state_dir / 'pending.json').exists():
            print(json.dumps(dict(at=utcnow(), status='HOLD', reason='OPERATOR_RECOVERY_REQUIRED')))
            return 'HOLD'
        try:
            success = state_dir / 'success.json'
            require(not success.is_symlink(), 'SUCCESS_STATE_SYMLINK')
            previous = json.loads(success.read_text()) if success.exists() else None
            release, publisher = api.candidate()
            decision = validate_release(api, release, publisher, previous, approvers)
            print(json.dumps(dict(at=utcnow(), event='checked', sha=release['sha'],
                                  previous_sha=previous['sha'] if previous else None, ci='PASS', decision=decision)))
            if decision == 'UNCHANGED': return 'UNCHANGED'
            envfile = root / '.env'
            require(envfile.is_file() and not envfile.is_symlink(), 'ENV_FILE_REQUIRED')
            if os.name == 'posix':
                info = envfile.stat()
                require(stat.S_IMODE(info.st_mode) == 0o600 and info.st_uid == os.getuid(), 'ENV_PERMISSION_REQUIRED')
            base = root / 'compose.yaml'
            env_before = hashlib.sha256(envfile.read_bytes()).digest()
            compose_before = hashlib.sha256(base.read_bytes()).digest()
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(('POSTGRES_', 'COMPOSE_')) and k not in ('APP_ENV', 'APP_VERSION')}
            env.update(DEPLOY_SHA=release['sha'], FRONTEND_IMAGE=release['images']['frontend'],
                       BACKEND_IMAGE=release['images']['backend'])
            compose = ['docker', 'compose', '--project-name', PROJECT, '--project-directory', str(root),
                       '--env-file', str(envfile), '-f', str(base),
                       '-f', str(root / 'automation' / 'compose.release.yaml')]
            # Persist before any Docker access: SIGKILL/reboot cannot trigger an automatic retry.
            atomic_json(state_dir / 'pending.json', dict(at=utcnow(), sha=release['sha'],
                        images=release['images'], previous_sha=previous['sha'] if previous else None))
            before_rows = service_rows(runner, compose, env)
            db_before = [s for s in before_rows if s['Service'] == 'db']
            require(len(db_before) == 1 and db_before[0]['State'] == 'running'
                    and db_before[0].get('Health') == 'healthy', 'EXISTING_DATABASE_NOT_HEALTHY')
            db_id = db_before[0]['ID']
            image_ids = {}
            print(json.dumps(dict(at=utcnow(), event='deploy-start', sha=release['sha'], images=release['images'])))
            for service in SERVICES:
                image = release['images'][service]
                if not previous or previous['images'].get(service) != image:
                    runner(['docker', 'pull', image], env=env)
                inspected = json.loads(runner(['docker', 'image', 'inspect', image], env=env))
                require(image in inspected[0].get('RepoDigests', []), 'PULLED_DIGEST_MISMATCH')
                image_ids[service] = inspected[0]['Id']
            # --no-deps never touches db; no down, remove-orphans, force-recreate or build.
            runner(compose + ['up', '-d', '--no-build', '--no-deps', '--pull', 'never', 'frontend', 'backend'], env=env)
            health(release['sha'])
            for attempt in range(12):
                rows = service_rows(runner, compose, env)
                if all(len([s for s in rows if s['Service'] == service and s['State'] == 'running'
                            and s.get('Health') == 'healthy']) == 1 for service in ('frontend', 'backend', 'db')):
                    break
                if attempt < 11: time.sleep(5)
            for service in ('frontend', 'backend', 'db'):
                matching = [s for s in rows if s['Service'] == service]
                require(len(matching) == 1 and matching[0]['State'] == 'running'
                        and matching[0].get('Health') == 'healthy', 'SERVICE_NOT_HEALTHY')
                if service == 'db':
                    require(matching[0]['ID'] == db_id, 'DATABASE_CONTAINER_CHANGED')
                else:
                    running_id = runner(['docker', 'inspect', '--format', '{{.Image}}', matching[0]['ID']], env=env).strip()
                    require(running_id == image_ids[service], 'RUNNING_IMAGE_MISMATCH')
            require(hashlib.sha256(envfile.read_bytes()).digest() == env_before
                    and hashlib.sha256(base.read_bytes()).digest() == compose_before, 'PROTECTED_FILE_CHANGED')
            record = dict(release, deployed_at=utcnow(), status='PASS', health='PASS')
            if previous: atomic_json(state_dir / 'previous.json', previous)
            atomic_json(success, record)
            (state_dir / 'pending.json').unlink()
            sync_directory(state_dir)
            print(json.dumps(dict(at=utcnow(), event='deploy-end', sha=release['sha'], status='PASS')))
            return 'PASS'
        except Exception as exc:
            reason = str(exc) if isinstance(exc, Hold) else 'UNEXPECTED_FAILURE'
            failure = dict(at=utcnow(), status='HOLD', reason=reason,
                           previous_sha=previous.get('sha') if previous else None,
                           sha=release.get('sha') if isinstance(release, dict) else None)
            # Polling prerequisites may recover next minute; attempted deployments require operator recovery.
            name = 'hold.json' if (state_dir / 'pending.json').exists() else 'last-check.json'
            atomic_json(state_dir / name, failure)
            print(json.dumps(failure))
            return 'HOLD'


def main():
    try:
        require(os.name == 'posix' and ROOT.is_dir() and not ROOT.is_symlink(), 'LINUX_POC_DIRECTORY_REQUIRED')
        require(platform.machine() in ('x86_64', 'amd64'), 'AMD64_SERVER_REQUIRED')
        config = json.loads((ROOT / 'automation' / 'config.json').read_text())
        require(config.get('enabled') is True, 'DEPLOYMENT_NOT_ENABLED')
        require(config['compose_sha256'] == hashlib.sha256((ROOT / 'compose.yaml').read_bytes()).hexdigest(), 'COMPOSE_BASELINE_MISMATCH')
        # Credentials are provisioned separately by the operator, never from the PoC .env.
        credentials = Path(os.environ['CREDENTIALS_DIRECTORY']) / 'github-token'
        api = GitHub(credentials.read_text())
        approvers = {s.lower() for s in config['approved_mergers'] if re.fullmatch('[A-Za-z0-9-]+', s)}
        result = execute(api, ROOT, approvers)
        return 0 if result in ('PASS', 'UNCHANGED', 'LOCKED') else 1
    except Exception:
        print(json.dumps(dict(at=utcnow(), status='HOLD', reason='PREFLIGHT_FAILED')))
        return 1


if __name__ == '__main__':
    sys.exit(main())
