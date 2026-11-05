"""Exercise real policy/adapters with only network and Docker boundaries replaced."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import deploy
import publish
from test_deploy import FakeGitHub, SHA, OLD, REPO, release


class BoundaryTests(unittest.TestCase):
    def test_atomic_state_syncs_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'pending.json'
            with patch.object(deploy, 'sync_directory', create=True) as sync:
                deploy.atomic_json(path, {'sha': SHA})
                sync.assert_called_once_with(path.parent)
                self.assertEqual(json.loads(path.read_text())['sha'], SHA)

    def event(self, api):
        return dict(repository={'full_name': REPO}, workflow_run=dict(api.ci))

    def test_publish_authorized_ci_success(self):
        api = FakeGitHub()
        self.assertEqual(publish.preflight(api, self.event(api), SHA, {'approved-pm'}), SHA)

    def test_publish_blocks_ci_failure_pending_fork_and_sha_race(self):
        for field, value in [('conclusion', 'failure'), ('status', 'in_progress'),
                             ('head_branch', 'feature'), ('event', 'pull_request')]:
            with self.subTest(field=field):
                api = FakeGitHub(); api.ci[field] = value
                with self.assertRaises(deploy.Hold):
                    publish.preflight(api, self.event(api), SHA, {'approved-pm'})
        api = FakeGitHub()
        with self.assertRaises(deploy.Hold): publish.preflight(api, self.event(api), OLD, {'approved-pm'})

    def test_publish_blocks_missing_approver(self):
        api = FakeGitHub()
        with self.assertRaises(deploy.Hold): publish.preflight(api, self.event(api), SHA, set())

    def artifact_api(self, manifest=release(), wrong_digest=False):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as archive:
            archive.writestr('release.json', json.dumps(manifest))
        data = buf.getvalue()
        api = deploy.GitHub('test-only-token')
        fake = FakeGitHub()
        def request(path, raw=False):
            if path.endswith('/zip'): return data
            if '/artifacts?' in path:
                return dict(total_count=1, artifacts=[dict(id=99, name=deploy.ARTIFACT,
                    expired=False, workflow_run={'id':20},
                    digest='sha256:' + ('0'*64 if wrong_digest else hashlib.sha256(data).hexdigest()))])
            if '/workflows/' in path: return {'workflow_runs': [fake.publisher]}
            return fake.publisher
        api.request = request
        return api

    def test_artifact_archive_digest_validated(self):
        manifest, run = self.artifact_api().candidate()
        self.assertEqual(manifest['sha'], SHA); self.assertEqual(run['id'], 20)

    def test_artifact_archive_digest_mismatch_blocks(self):
        with self.assertRaises(deploy.Hold): self.artifact_api(wrong_digest=True).candidate()

    def test_api_full_pull_details_used_for_merger(self):
        api = deploy.GitHub('test-only-token')
        calls = []
        def request(path):
            calls.append(path)
            return [{'number':1, 'merged_at':'time'}] if '/commits/' in path else FakeGitHub().pr
        api.request = request
        self.assertEqual(api.merged_pulls(SHA)[0]['merged_by']['login'], 'approved-pm')
        self.assertEqual(calls[-1], '/repos/' + REPO + '/pulls/1')

    def test_redirect_does_not_forward_token(self):
        import urllib.request
        req = urllib.request.Request('https://api.github.com/artifact', headers={'Authorization':'Bearer test-only'})
        redirected = deploy.SafeRedirect().redirect_request(req, None, 302, '', {}, 'https://example.blob.core.windows.net/archive')
        self.assertFalse(redirected.has_header('Authorization'))

    def test_health_version_mismatch_retries_then_fails(self):
        class Response:
            status = 200
            def __init__(self, url): self.url = url
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self, n): return json.dumps({'version':OLD}).encode()
        calls = []
        class Opener:
            def open(self, url, timeout):
                calls.append((url, timeout)); return Response(url)
        with patch.object(deploy.urllib.request, 'build_opener', return_value=Opener()), patch.object(deploy.time, 'sleep') as sleep:
            with self.assertRaises(deploy.Hold): deploy.check_health(SHA)
            self.assertEqual(sleep.call_count, 5)
            self.assertEqual(len(calls), 18)
            self.assertTrue(all(timeout == 3 for _, timeout in calls))


if __name__ == '__main__': unittest.main()
