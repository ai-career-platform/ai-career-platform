"""Reject malformed approval configuration before any external side effects."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import deploy
import publish
from test_deploy import FakeGitHub, SHA, release

INVALID = [
    'approved-pm', 123, True, {'approved-pm': True}, None, [], [''],
    ['approved-pm', 123], ['approved-pm', None], ['approved-pm', {}],
    ['approved-pm', ''], ['approved-pm', ' invalid'], ['a_b'], ['a.b'],
    ['-login'], ['login-'], ['two--hyphens'], ['a' * 40], ['계정'], ['login\n'],
    ['approved-pm', False], ['approved-pm', []], [' '], 1.5,
]


class ApproverTests(unittest.TestCase):
    def test_valid_array_normalizes_case_and_duplicates(self):
        self.assertEqual(deploy.validate_approvers(['Approved-PM', 'APPROVED-pm', 'approved-jm']),
                         {'approved-pm', 'approved-jm'})

    def test_valid_username_boundaries(self):
        self.assertEqual(deploy.validate_approvers(['a', '1', 'a' * 39, 'a-b-c']),
                         {'a', '1', 'a' * 39, 'a-b-c'})

    def test_invalid_configuration_rejected_entirely(self):
        for value in INVALID:
            with self.subTest(value=value), self.assertRaises(deploy.Hold):
                deploy.validate_approvers(value)

    def test_normalized_approver_passes_both_policies(self):
        api = FakeGitHub()
        approved = deploy.validate_approvers(['APPROVED-PM', 'approved-pm'])
        event = dict(repository={'full_name': deploy.REPO}, workflow_run=dict(api.ci))
        self.assertEqual(publish.preflight(api, event, SHA, approved), SHA)
        self.assertEqual(deploy.validate_release(api, release(), api.publisher, None, approved), 'APPROVED')

    def test_unlisted_merger_still_blocked(self):
        api = FakeGitHub()
        api.pr['merged_by']['login'] = 'unlisted'
        approved = deploy.validate_approvers(['approved-pm'])
        event = dict(repository={'full_name': deploy.REPO}, workflow_run=dict(api.ci))
        with self.assertRaises(deploy.Hold): publish.preflight(api, event, SHA, approved)
        with self.assertRaises(deploy.Hold): deploy.validate_release(api, release(), api.publisher, None, approved)

    def test_valid_publisher_entrypoint_uses_normalized_mapping(self):
        api = FakeGitHub()
        event = dict(repository={'full_name': deploy.REPO}, workflow_run=dict(api.ci))
        with patch.dict(os.environ, {'APPROVED_MERGERS':'["APPROVED-PM", "approved-pm"]',
                'GH_TOKEN':'fixture-only', 'GITHUB_SHA':SHA, 'GITHUB_EVENT_PATH':'fixture-event',
                'WRITE_MANIFEST':'0'}), patch.object(publish.Path, 'read_text', return_value=json.dumps(event)), \
                patch.object(publish, 'GitHub', return_value=api), patch.object(publish.Path, 'write_text') as write:
            publish.main()
            write.assert_not_called()

    def test_malformed_json_publisher_never_creates_api(self):
        for raw in ['', 'not-json', '["approved-pm",]']:
            with self.subTest(raw=raw), patch.dict(os.environ, {'APPROVED_MERGERS':raw,
                    'GITHUB_EVENT_PATH':'fixture-event'}), \
                    patch.object(publish.Path, 'read_text', return_value='{}'), \
                    patch.object(publish, 'GitHub') as github:
                with self.assertRaises(json.JSONDecodeError): publish.main()
                github.assert_not_called()

    def test_valid_deployer_entrypoint_passes_normalized_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = dict(enabled=True, compose_sha256='fixture-hash',
                          approved_mergers=['APPROVED-PM', 'approved-pm'])
            with patch.object(deploy, 'ROOT', root), \
                    patch.object(deploy, 'os', SimpleNamespace(name='posix', environ=os.environ)), \
                    patch.object(deploy.platform, 'machine', return_value='x86_64'), \
                    patch.object(type(root), 'read_text', return_value=json.dumps(config)), \
                    patch.object(type(root), 'read_bytes', return_value=b'fixture-compose'), \
                    patch.object(deploy.hashlib, 'sha256') as sha256, \
                    patch.dict(os.environ, {'CREDENTIALS_DIRECTORY':tmp}), \
                    patch.object(deploy, 'GitHub') as github, \
                    patch.object(deploy, 'execute', return_value='UNCHANGED') as execute:
                sha256.return_value.hexdigest.return_value = 'fixture-hash'
                self.assertEqual(deploy.main(), 0)
                execute.assert_called_once_with(github.return_value, root, {'approved-pm'})

    def test_invalid_publisher_config_never_creates_api_or_manifest(self):
        for value in INVALID:
            with self.subTest(value=value), patch.dict(os.environ, {
                'APPROVED_MERGERS': json.dumps(value), 'GH_TOKEN': 'fixture-only',
                'GITHUB_SHA': SHA, 'GITHUB_EVENT_PATH': 'fixture-event', 'WRITE_MANIFEST': '1',
            }), patch.object(publish.Path, 'read_text', return_value='{}'), \
                    patch.object(publish, 'GitHub') as github, \
                    patch.object(publish, 'preflight') as preflight, \
                    patch.object(publish.Path, 'write_text') as write:
                with self.assertRaises(deploy.Hold): publish.main()
                github.assert_not_called(); preflight.assert_not_called(); write.assert_not_called()

    def test_invalid_deployer_config_never_creates_api_or_deploys(self):
        # Substitute only OS/preflight boundaries; configuration validation is real.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for value in INVALID:
                config = dict(enabled=True, compose_sha256='fixture-hash', approved_mergers=value)
                with self.subTest(value=value), patch.object(deploy, 'ROOT', root), \
                        patch.object(deploy, 'os', SimpleNamespace(name='posix', environ=os.environ)), \
                        patch.object(deploy.platform, 'machine', return_value='x86_64'), \
                        patch.object(type(root), 'read_text', return_value=json.dumps(config)), \
                        patch.object(type(root), 'read_bytes', return_value=b'fixture-compose'), \
                        patch.object(deploy.hashlib, 'sha256') as sha256, \
                        patch.dict(os.environ, {'CREDENTIALS_DIRECTORY': tmp}), \
                        patch.object(deploy, 'GitHub') as github, \
                        patch.object(deploy, 'execute') as execute, patch('builtins.print'):
                    sha256.return_value.hexdigest.return_value = 'fixture-hash'
                    self.assertEqual(deploy.main(), 1)
                    github.assert_not_called(); execute.assert_not_called()


if __name__ == '__main__': unittest.main()
