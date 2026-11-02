"""A commit in the main branch is code evidence, never a functional test."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)  # no console flashing when the app runs under pythonw


def _git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, timeout=20, creationflags=_NO_WINDOW)


def verify_deliveries(store, repo_roots):
    """Only inspect explicitly mapped local repositories; never fetch or checkout.

    Branch/head per repository and the answer per (repository, commit) are asked once per run: hundreds of deliveries
    share a few repositories, and each git process costs a fraction of a second on Windows."""
    results = []
    heads, answers = {}, {}
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
                if root not in heads:
                    branch = next((b for b in ('main', 'master') if _git(root, 'show-ref', '--verify', '--quiet', 'refs/heads/' + b).returncode == 0), None)
                    heads[root] = (branch, _git(root, 'rev-parse', 'refs/heads/' + branch).stdout.strip() if branch else '')
                branch, head = heads[root]
                if (root, sha) not in answers:
                    commit = _git(root, 'rev-parse', '--verify', sha + '^{commit}')
                    full = commit.stdout.strip() if not commit.returncode else ''
                    code = _git(root, 'merge-base', '--is-ancestor', full, head).returncode if (full and branch) else None
                    answers[(root, sha)] = (full, code)
                full, code = answers[(root, sha)]
                if not full:
                    result['reason'] = 'commit_not_found'
                elif not branch:
                    result['reason'] = 'main_branch_not_found'
                else:
                    result.update(commit=full, branch=branch, main_head=head)
                    if code in (0, 1):
                        result['status'] = 'integrated' if code == 0 else 'not_in_main'
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
