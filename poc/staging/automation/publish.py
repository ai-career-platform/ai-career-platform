"""Trusted main-only publisher gates and manifest generation. No Docker execution here."""
import json
import os
from pathlib import Path
import re

from deploy import GitHub, REPO, CI_WORKFLOW, require


def preflight(api, event, expected_sha, approvers):
    run = event['workflow_run']
    sha = run['head_sha']
    require(bool(approvers), 'APPROVER_MAPPING_REQUIRED')
    require(event['repository']['full_name'] == REPO and run['repository']['full_name'] == REPO, 'WRONG_REPOSITORY')
    require(run['head_branch'] == 'main' and run['event'] == 'push', 'MAIN_PUSH_REQUIRED')
    require(run['status'] == 'completed' and run['conclusion'] == 'success', 'CI_SUCCESS_REQUIRED')
    require(run['path'] == CI_WORKFLOW and re.fullmatch('[0-9a-f]{40}', sha), 'INVALID_CI_SOURCE')
    # Fail closed if main advanced between the CI run and workflow_run scheduling.
    require(sha == expected_sha, 'PUBLISHER_SHA_RACE')
    fresh = api.run(run['id'])
    require(fresh['head_sha'] == sha and fresh['conclusion'] == 'success'
            and fresh['status'] == 'completed' and fresh['event'] == 'push'
            and fresh['head_branch'] == 'main' and fresh['path'] == CI_WORKFLOW
            and fresh['repository']['full_name'] == REPO, 'CI_RECHECK_FAILED')
    jobs = [j for j in api.ci_jobs(run['id']) if j['name'] == 'CI Smoke Test']
    require(len(jobs) == 1 and jobs[0]['status'] == 'completed' and jobs[0]['conclusion'] == 'success', 'CI_JOB_REQUIRED')
    require(any(p.get('merged_at') and p.get('merge_commit_sha') == sha
                and p['base']['ref'] == 'main' and p['base']['repo']['full_name'] == REPO
                and (p.get('merged_by') or {}).get('login', '').lower() in approvers
                for p in api.merged_pulls(sha)), 'AUTHORIZED_MERGE_REQUIRED')
    return sha


def main():
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    approved = {s.lower() for s in json.loads(os.environ['APPROVED_MERGERS'])}
    sha = preflight(GitHub(os.environ['GH_TOKEN']), event, os.environ['GITHUB_SHA'], approved)
    if os.environ.get('WRITE_MANIFEST') == '1':
        images = {}
        for service in ('frontend', 'backend'):
            digest = os.environ[service.upper() + '_DIGEST']
            require(re.fullmatch('sha256:[0-9a-f]{64}', digest), 'INVALID_BUILD_DIGEST')
            images[service] = f'ghcr.io/ai-career-platform/ai-career-platform-{service}@{digest}'
        manifest = dict(schema=1, repository=REPO, branch='main', sha=sha,
                        ci_run_id=event['workflow_run']['id'],
                        publish_run_id=int(os.environ['GITHUB_RUN_ID']),
                        run_number=int(os.environ['GITHUB_RUN_NUMBER']), images=images)
        Path('release.json').write_text(json.dumps(manifest, sort_keys=True) + '\n')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('HOLD: publication gate or manifest creation failed') from None
