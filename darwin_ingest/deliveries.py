"""A commit in the main branch is code evidence, never a functional test."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


def _git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, timeout=20)


def verify_deliveries(store, repo_roots):
    """Only inspect explicitly mapped local repositories; never fetch or checkout."""
    results = []
    for delivery in store.q('SELECT * FROM deliveries ORDER BY id'):
        sha = delivery.get('commit_sha') or ''
        root = repo_roots.get(delivery.get('repo'))
        result = {'delivery_id': delivery['id'], 'commit': sha, 'status': 'unknown', 'functional_verification': 'unchanged'}
        if not root:
            result['reason'] = 'repository_not_mapped'
        elif not re.fullmatch(r'[0-9a-fA-F]{7,64}', sha):
            result['reason'] = 'invalid_commit_id'
        else:
            try:
                root = Path(root).resolve(strict=True)
                branch = next((b for b in ('main', 'master') if _git(root, 'show-ref', '--verify', '--quiet', 'refs/heads/' + b).returncode == 0), None)
                commit = _git(root, 'rev-parse', '--verify', sha + '^{commit}')
                if commit.returncode:
                    result['reason'] = 'commit_not_found'
                elif not branch:
                    result['reason'] = 'main_branch_not_found'
                else:
                    head = _git(root, 'rev-parse', 'refs/heads/' + branch)
                    ancestry = _git(root, 'merge-base', '--is-ancestor', commit.stdout.strip(), head.stdout.strip())
                    result.update(commit=commit.stdout.strip(), branch=branch, main_head=head.stdout.strip())
                    if ancestry.returncode in (0, 1):
                        result['status'] = 'integrated' if ancestry.returncode == 0 else 'not_in_main'
                    else:
                        result['reason'] = 'ancestry_failed'
            except (OSError, subprocess.TimeoutExpired):
                result['reason'] = 'repository_unavailable'
        evidence = delivery.get('evidence') or {}
        if not isinstance(evidence, dict):
            evidence = {'original': evidence}
        evidence['commit_ancestry'] = result
        with store.tx() as connection:
            connection.execute('UPDATE deliveries SET evidence=? WHERE id=?', (json.dumps(evidence, ensure_ascii=False), delivery['id']))
        if result['status'] == 'integrated':
            # Superseded deliveries remain superseded even when their commit exists.
            if delivery['implementation'] != 'sustituida':
                store.set_state('deliveries', delivery['id'], 'implementation', 'integrada', by='ancestry', note='Commit is in ' + result['branch'] + '; functional verification unchanged')
        results.append(result)
    return {'deliveries': results}
