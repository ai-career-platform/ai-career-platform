import copy
from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('deploy', HERE / 'deploy.py')
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)
SHA = 'a' * 40
OLD = 'b' * 40
DIGEST = 'sha256:' + '1' * 64
REPO = 'ai-career-platform/ai-career-platform'


def release():
    return dict(schema=1, repository=REPO, branch='main', sha=SHA,
                ci_run_id=10, publish_run_id=20, run_number=2,
                images={s: f'ghcr.io/ai-career-platform/ai-career-platform-{s}@{DIGEST}'
                        for s in ('frontend', 'backend')})


class FakeGitHub:
    def __init__(self):
        self.manifest = release()
        self.ci = dict(status='completed', conclusion='success', event='push',
                       head_branch='main', head_sha=SHA, path='.github/workflows/ci.yml',
                       repository={'full_name': REPO}, id=10)
        self.publisher = dict(status='completed', conclusion='success', event='workflow_run',
                              head_branch='main', head_sha=SHA,
                              path='.github/workflows/staging-publish.yml',
                              repository={'full_name': REPO}, id=20, run_number=2)
        self.jobs = [dict(name='CI Smoke Test', status='completed', conclusion='success')]
        self.pr = dict(merged_at='2026-11-05T00:00:00Z', merge_commit_sha=SHA,
                       base={'ref': 'main', 'repo': {'full_name': REPO}},
                       merged_by={'login': 'approved-pm'})
        self.forward = True

    def candidate(self): return copy.deepcopy(self.manifest), self.publisher
    def run(self, run_id): return self.ci if run_id == 10 else self.publisher
    def ci_jobs(self, run_id): return self.jobs
    def merged_pulls(self, sha): return [self.pr]
    def is_forward(self, old, new): return self.forward


class DeployTests(unittest.TestCase):
    def setUp(self):
        self.silent = patch('builtins.print')
        self.silent.start()
        self.addCleanup(self.silent.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = self.root / '.env'
        self.env.write_text('POSTGRES_PASSWORD=preserved-secret\n')
        self.env.chmod(0o600)
        self.compose = self.root / 'compose.yaml'
        self.compose.write_text('preserve original DB volume and network')
        self.api = FakeGitHub()
        self.commands = []
        self.db_id = 'db-original'
        self.running_image = 'sha256:actual-image-id'
        def run(args, **kwargs):
            self.commands.append(args)
            if 'image' in args: return json.dumps([{'RepoDigests': [args[-1]], 'Id': 'sha256:actual-image-id'}])
            if 'inspect' in args: return self.running_image
            if 'ps' in args:
                return '\n'.join(json.dumps(dict(Service=s, State='running', Health='healthy', ID=self.db_id if s=='db' else s))
                                 for s in ['frontend', 'backend', 'db'])
            return ''
        self.runner = run
        self.health = lambda sha: None

    def tearDown(self): self.tmp.cleanup()
    def invoke(self, lock=True):
        return deploy.execute(self.api, self.root, {'approved-pm'}, runner=self.runner,
                              health=self.health, locker=lambda p: nullcontext(lock))

    def state(self):
        return json.loads((self.root / '.deploy-state' / 'success.json').read_text())

    def old_state(self, **changes):
        state = dict(sha=OLD, run_number=1, images={})
        state.update(changes)
        d = self.root / '.deploy-state'; d.mkdir(exist_ok=True)
        (d / 'success.json').write_text(json.dumps(state))

    def test_success_records_sha_and_preserves_env_and_compose(self):
        self.assertEqual(self.invoke(), 'PASS')
        self.assertEqual(self.state()['sha'], SHA)
        self.assertEqual(self.env.read_text(), 'POSTGRES_PASSWORD=preserved-secret\n')
        self.assertEqual(self.compose.read_text(), 'preserve original DB volume and network')
        ups = [c for c in self.commands if 'up' in c]
        self.assertEqual(len(ups), 1)
        self.assertEqual(ups[0][-2:], ['frontend', 'backend'])
        self.assertIn('--no-deps', ups[0]); self.assertIn('--no-build', ups[0])
        self.assertNotIn('db', ups[0]); self.assertNotIn('--force-recreate', ups[0])

    def test_same_sha_no_docker(self):
        self.old_state(sha=SHA, run_number=2, images=release()['images'])
        self.assertEqual(self.invoke(), 'UNCHANGED'); self.assertEqual(self.commands, [])

    def test_ci_fail_blocks(self):
        self.api.ci['conclusion'] = 'failure'
        self.assertEqual(self.invoke(), 'HOLD'); self.assertFalse(self.commands)

    def test_ci_pending_blocks(self):
        self.api.ci.update(status='in_progress', conclusion=None)
        self.assertEqual(self.invoke(), 'HOLD'); self.assertFalse(self.commands)

    def test_repository_mismatch_blocks(self):
        self.api.manifest['repository'] = 'attacker/repo'
        self.assertEqual(self.invoke(), 'HOLD'); self.assertFalse(self.commands)

    def test_branch_mismatch_blocks(self):
        self.api.manifest['branch'] = 'feature'
        self.assertEqual(self.invoke(), 'HOLD'); self.assertFalse(self.commands)

    def test_lock_collision_no_state_or_docker(self):
        self.assertEqual(self.invoke(False), 'LOCKED'); self.assertFalse(self.commands)
        self.assertFalse((self.root / '.deploy-state' / 'success.json').exists())

    def test_pull_failure_latches_hold_and_preserves_success(self):
        self.old_state()
        def fail(*a, **k): raise RuntimeError('secret must never be logged')
        self.runner = fail
        self.assertEqual(self.invoke(), 'HOLD'); self.assertEqual(self.state()['sha'], OLD)
        self.assertEqual(self.invoke(), 'HOLD')
        failure = (self.root / '.deploy-state' / 'hold.json').read_text()
        self.assertNotIn('secret', failure)

    def test_health_failure_no_success_and_no_auto_retry(self):
        self.health = lambda s: (_ for _ in ()).throw(RuntimeError('health'))
        self.assertEqual(self.invoke(), 'HOLD')
        count = len(self.commands)
        self.assertEqual(self.invoke(), 'HOLD'); self.assertEqual(len(self.commands), count)
        self.assertFalse((self.root / '.deploy-state' / 'success.json').exists())

    def test_rewind_blocks(self):
        self.old_state(); self.api.forward = False
        self.assertEqual(self.invoke(), 'HOLD'); self.assertFalse(self.commands)

    def test_old_run_blocks(self):
        self.old_state(run_number=3)
        self.assertEqual(self.invoke(), 'HOLD'); self.assertFalse(self.commands)

    def test_unapproved_merger_blocks(self):
        self.api.pr['merged_by']['login'] = 'unknown'
        self.assertEqual(self.invoke(), 'HOLD'); self.assertFalse(self.commands)

    def test_missing_approvers_blocks(self):
        self.assertEqual(deploy.execute(self.api, self.root, set(), runner=self.runner,
                         health=self.health, locker=lambda p: nullcontext(True)), 'HOLD')
        self.assertFalse(self.commands)

    def test_wrong_digest_blocks(self):
        self.api.manifest['images']['backend'] = 'ghcr.io/evil/backend:latest'
        self.assertEqual(self.invoke(), 'HOLD'); self.assertFalse(self.commands)

    def test_wrong_ci_job_blocks(self):
        self.api.jobs[0]['name'] = 'unrelated'
        self.assertEqual(self.invoke(), 'HOLD'); self.assertFalse(self.commands)

    def test_ci_sha_mismatch_blocks(self):
        self.api.ci['head_sha'] = OLD
        self.assertEqual(self.invoke(), 'HOLD'); self.assertFalse(self.commands)

    def test_publisher_not_success_blocks(self):
        self.api.publisher['conclusion'] = 'failure'
        self.assertEqual(self.invoke(), 'HOLD'); self.assertFalse(self.commands)

    def test_same_sha_changed_digest_blocks(self):
        self.old_state(sha=SHA, images={})
        self.assertEqual(self.invoke(), 'HOLD'); self.assertFalse(self.commands)

    def test_unchanged_digest_new_sha_no_docker(self):
        self.old_state(images=release()['images'])
        self.assertEqual(self.invoke(), 'HOLD'); self.assertFalse(self.commands)

    def test_running_image_mismatch_no_success(self):
        self.running_image = 'sha256:unexpected'
        self.assertEqual(self.invoke(), 'HOLD')
        self.assertFalse((self.root / '.deploy-state' / 'success.json').exists())

    def test_database_container_replacement_blocks_success(self):
        original = self.runner
        def changed(args, **kwargs):
            if 'up' in args: self.db_id = 'unexpected-new-db'
            return original(args, **kwargs)
        self.runner = changed
        self.assertEqual(self.invoke(), 'HOLD')
        self.assertFalse((self.root / '.deploy-state' / 'success.json').exists())

    def test_interrupted_deployment_blocks_retry(self):
        d = self.root / '.deploy-state'; d.mkdir()
        (d / 'pending.json').write_text(json.dumps({'sha':SHA}))
        self.assertEqual(self.invoke(), 'HOLD'); self.assertFalse(self.commands)

    def test_pending_publication_recovers_on_next_poll_without_manual_reset(self):
        self.api.publisher['status'] = 'in_progress'
        self.assertEqual(self.invoke(), 'HOLD'); self.assertFalse(self.commands)
        self.api.publisher['status'] = 'completed'
        self.assertEqual(self.invoke(), 'PASS')




class SelectPublishRunTests(unittest.TestCase):
    """F-07: a skipped publish run (older merge's CI finished last) must not wedge Auto-CD."""

    def run_(self, rid, status, conclusion):
        return {'id': rid, 'status': status, 'conclusion': conclusion}

    def test_skipped_newest_is_passed_over(self):
        runs = [self.run_(2, 'completed', 'skipped'), self.run_(1, 'completed', 'success')]
        self.assertEqual(deploy.select_publish_run(runs)['id'], 1)

    def test_newer_failed_or_pending_still_blocks(self):
        for status, conclusion in (('completed', 'failure'), ('in_progress', None), ('completed', 'cancelled')):
            runs = [self.run_(3, 'completed', 'skipped'), self.run_(2, status, conclusion), self.run_(1, 'completed', 'success')]
            self.assertEqual(deploy.select_publish_run(runs)['id'], 2)

    def test_no_real_run_holds(self):
        for runs in ([], [self.run_(1, 'completed', 'skipped')]):
            with self.assertRaises(deploy.Hold) as raised:
                deploy.select_publish_run(runs)
            self.assertEqual(str(raised.exception), 'NO_PUBLISHED_RELEASE')


if __name__ == '__main__': unittest.main()
