"""A commit in the main branch is code evidence, never a functional test.

Order of proof for each declared commit (cheapest and strongest first):
1. the commit is in the main branch of the repository the delivery names (directly or through the alias map);
2. the commit lives in another local repository (multi-repository tasks, old names) and is in that one's main;
3. the commit exists (another branch, an unreachable object, another repository) but main holds an equivalent:
   same ``git patch-id`` (rebased or cherry-picked), or failing that same subject and author date;
4. the commit is gone (history rewritten, branch deleted) and the delivery's Ágora task names the commit that
   reached main (« Integrado en master (sha) », the last submission's « Commits: » line, the task's commit list);
5. the code was folded into another app as a subfolder without its history: « imported », with the import commit.
Anything else stays « unknown » with the reason, or « not_in_main »."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping, Optional


_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)  # no console flashing when the app runs under pythonw
_SHA = re.compile(r'[0-9a-fA-F]{7,64}')
_TASK_REF = re.compile(r'#(\d{1,6})\b')
#: « Integrado en master (79550b71) », « Integrada en Prospero main 1dae187 (ff desde …) », « integrado en HoardLink main 73d3e1e ».
_INTEGRATED_AS = re.compile(r"integrad[oa]s?\s+en\s+(?:(?P<repo>[\w'’ .-]{1,40}?)\s+)?(?:main|master)\b[^\n0-9a-fA-F]{0,12}?\(?"
                            r"(?P<ids>[0-9a-fA-F]{7,40}(?:[\s,+y]+[0-9a-fA-F]{7,40})*)\)?", re.I)
#: « 72a6658c -> 4ab094ea… » (old → new, e.g. after a cherry-pick), optionally on a line « - Tantalus's Hoard main: … ».
_PAIR = re.compile(r'\b([0-9a-fA-F]{7,40})\s*(?:->|→|=>)\s*([0-9a-fA-F]{7,40})\b')
_REPO_LINE = re.compile(r"^[\s\-*•]*(?P<repo>[^:\n]{2,60}?)\s+(?:main|master)\s*:(?P<rest>.*)$", re.M)
#: « Integrado: HoardLink main 70d1578, Tantalus main 57da1e2 y Faustus master dae07fc7 » — which repository got which id.
_REPO_SHA = re.compile(r"(?P<repo>[A-Z][\w'’.-]*(?:\s[A-Z][\w'’.-]*){0,3})\s+(?:main|master)\s+\(?(?P<sha>[0-9a-fA-F]{7,40})\b")
#: A resolution that closes the task without integrating it (« Cierre sin integrar », « cerrada sin integrar »,
#: « Descartada por acuerdo »).
_NOT_INTEGRATED = re.compile(r'(?:cierre|cerrad[ao]s?)\s+sin\s+integrar|\bno\s+se\s+integr[óo]\b|\bdescartad[ao]s?\s+por\s+acuerdo\b', re.I)
_CHERRY = re.compile(r'cherry picked from commit ([0-9a-fA-F]{7,40})')
_COMMITS_LINE = re.compile(r'^Commits:\s*(.+)$', re.M)
#: Strength of each way of proving integration, strongest first; the weakest one used names the delivery's result.
VIA_ORDER = ('direct', 'other_repository', 'cherry_pick_trailer', 'patch_id', 'subject_date', 'agora_resolution', 'agora_submission', 'agora_task')


def _git(root, *args, input=None, timeout=20, binary=False):
    kw = {} if binary else {'text': True, 'encoding': 'utf-8', 'errors': 'replace'}
    return subprocess.run(['git', '-C', str(root), *args], input=input, capture_output=True, timeout=timeout,
                          creationflags=_NO_WINDOW, **kw)


def split_commits(value) -> Optional[list]:
    """« 7cc2354 5e8241b », « a, b », « a + b » → the ids; empty → []; anything that is not a list of ids → None."""
    text = str(value or '').strip()
    if not text:
        return []
    tokens = [t for t in re.split(r'[\s,;+/]+', text) if t and t.lower() != 'y']
    if tokens and all(_SHA.fullmatch(t) for t in tokens):
        return list(dict.fromkeys(t.lower() for t in tokens))
    return None


class _Repo:
    """One local repository, asked each question once per run (hundreds of deliveries share a few repositories and
    each git process costs a fraction of a second on Windows)."""

    def __init__(self, path, name=''):
        self.path = Path(path).resolve(strict=True)
        self.name = name or self.path.name
        self.branch = next((b for b in ('main', 'master')
                            if _git(self.path, 'show-ref', '--verify', '--quiet', 'refs/heads/' + b).returncode == 0), None)
        self.head = _git(self.path, 'rev-parse', 'refs/heads/' + self.branch).stdout.strip() if self.branch else ''
        self._full: dict = {}
        self._anc: dict = {}
        self._meta: dict = {}
        self._pid: dict = {}
        self._index = None
        self._cherry = None
        self._imports: dict = {}

    def resolve(self, shas) -> dict:
        """Full id of each abbreviated id that names a commit here (any ref or an unreachable object), else ''."""
        todo = [s for s in dict.fromkeys(shas) if s not in self._full]
        if todo:
            out = _git(self.path, 'cat-file', '--batch-check=%(objectname) %(objecttype)',
                       input=''.join(s + '^{commit}\n' for s in todo), timeout=120).stdout.splitlines()
            for s, line in zip(todo, out + [''] * len(todo)):
                parts = line.split()
                self._full[s] = parts[0] if len(parts) == 2 and parts[1] == 'commit' else ''
        return {s: self._full[s] for s in shas}

    def in_main(self, full):
        """0 when ``full`` is an ancestor of main, 1 when it is not, None when it could not be asked."""
        if not self.branch:
            return None
        if full not in self._anc:
            code = _git(self.path, 'merge-base', '--is-ancestor', full, self.head).returncode
            self._anc[full] = code if code in (0, 1) else None
        return self._anc[full]

    def meta(self, full):
        """(author time, subject) of a commit."""
        if full not in self._meta:
            out = _git(self.path, 'show', '-s', '--format=%at%x00%s', full).stdout.strip().split('\x00', 1)
            self._meta[full] = (int(out[0]), out[1]) if len(out) == 2 and out[0].isdigit() else (0, '')
        return self._meta[full]

    def patch_ids(self, fulls) -> dict:
        """Stable patch-id of each commit; merges and empty commits have none."""
        todo = [f for f in dict.fromkeys(fulls) if f not in self._pid]
        for i in range(0, len(todo), 100):
            chunk = todo[i:i + 100]
            for f in chunk:
                self._pid[f] = ''
            diff = _git(self.path, 'show', '--no-color', '--format=commit %H', '-p', *chunk, binary=True, timeout=120).stdout
            if diff:
                for line in _git(self.path, 'patch-id', '--stable', input=diff, binary=True, timeout=120).stdout.decode().splitlines():
                    pid, _, commit = line.partition(' ')
                    if commit.strip() in self._pid:
                        self._pid[commit.strip()] = pid
        return {f: self._pid[f] for f in fulls}

    def main_index(self):
        """(sha, author time, subject) of every commit in main."""
        if self._index is None:
            self._index = []
            if self.branch:
                for line in _git(self.path, 'log', self.head, '--format=%H%x00%at%x00%s', timeout=120).stdout.splitlines():
                    parts = line.split('\x00', 2)
                    if len(parts) == 3 and parts[1].isdigit():
                        self._index.append((parts[0], int(parts[1]), parts[2]))
        return self._index

    def cherry_picked(self, token):
        """Commit of main whose message says « (cherry picked from commit <token…>) » (``git cherry-pick -x``): proof of
        integration that survives the original being deleted."""
        if self._cherry is None:
            self._cherry = {}
            if self.branch:
                out = _git(self.path, 'log', self.head, '--grep=cherry picked from commit', '--format=%H%x00%B%x1e', timeout=120).stdout
                for block in out.split('\x1e'):
                    sha, _, body = block.strip().partition('\x00')
                    for orig in _CHERRY.findall(body):
                        self._cherry.setdefault(orig.lower(), sha)
        token = token.lower()
        return next(((orig, new) for orig, new in self._cherry.items() if orig.startswith(token)), None)

    def import_of(self, subdir):
        """First commit of main that added ``subdir`` (the commit that folded another app in), or None."""
        if subdir not in self._imports:
            out = _git(self.path, 'log', self.head, '--diff-filter=A', '--format=%H%x00%as', '--', subdir, timeout=60).stdout.splitlines() if self.branch else []
            last = out[-1].split('\x00') if out else []
            self._imports[subdir] = {'commit': last[0], 'date': last[1], 'subdir': subdir} if len(last) == 2 else None
        return self._imports[subdir]


#: Rebased or cherry-picked commits keep their author date; look this far after it (squashes, late integrations).
_WINDOW_BEFORE, _WINDOW_AFTER, _WINDOW_CAP = 86400, 30 * 86400, 600


def find_equivalent(origin: _Repo, full: str, target: _Repo) -> Optional[dict]:
    """A commit in ``target``'s main equivalent to ``full`` (which lives in ``origin``): same patch-id, else same subject
    and author date. Returns {'commit', 'method'} or None."""
    at, subject = origin.meta(full)
    if not at:
        return None
    pid = origin.patch_ids([full])[full]
    index = target.main_index()
    named = [c for c in index if c[0] != full and (c[2] == subject or c[1] == at)]
    window = [c for c in index if c[0] != full and at - _WINDOW_BEFORE <= c[1] <= at + _WINDOW_AFTER][:_WINDOW_CAP]
    if pid:
        for group in (named, window):
            ids = target.patch_ids([c[0] for c in group])
            hit = next((c[0] for c in group if ids.get(c[0]) == pid), None)
            if hit:
                return {'commit': hit, 'method': 'patch_id', 'patch_id': pid}
    hit = next((c[0] for c in named if c[2] == subject and c[1] == at), None)
    return {'commit': hit, 'method': 'subject_date'} if hit else None


def _norm(name) -> str:
    return re.sub(r's(?=hoard$)', '', re.sub(r'[^a-z0-9]', '', str(name or '').lower().replace("'s", '')))


def _weakest(vias):
    return max(vias, key=lambda v: VIA_ORDER.index(v) if v in VIA_ORDER else len(VIA_ORDER))


class _Verifier:
    def __init__(self, repo_roots: Mapping, agora_lookup: Optional[Callable[[int], Optional[dict]]] = None):
        self.targets: dict = {}
        for name, value in (repo_roots or {}).items():
            t = dict(value) if isinstance(value, Mapping) else {'path': value}
            if t.get('path') or t.get('search'):
                self.targets[str(name)] = {'path': str(t['path']) if t.get('path') else '', 'subdir': t.get('subdir') or '',
                                           'name': t.get('name') or str(name), 'search': bool(t.get('search')),
                                           'source_commit': t.get('source_commit') or ''}
        self.by_norm = {_norm(k): t for k, t in self.targets.items()}
        self.repos: dict = {}
        self.agora_lookup = agora_lookup
        self._tasks: dict = {}

    def target(self, name):
        if not name:
            return None
        # « Tantalus » / « Prospero » in a resolution are « Tantalus's Hoard » / « Prospero's Hoard ».
        return self.targets.get(str(name)) or self.by_norm.get(_norm(name)) or self.by_norm.get(_norm(f'{name} Hoard'))

    def repo(self, target):
        if not target or not target.get('path'):
            return None
        key = str(Path(target['path']).resolve())
        if key not in self.repos:
            try:
                self.repos[key] = _Repo(target['path'], target['name'] if not target['subdir'] else Path(key).name)
            except (OSError, subprocess.TimeoutExpired):
                self.repos[key] = None
        return self.repos[key]

    def all_repos(self):
        out = {}
        for t in self.targets.values():
            r = self.repo(t)
            if r is not None:
                out.setdefault(str(r.path), r)
        return list(out.values())

    def prefetch(self, tokens):
        tokens = list(dict.fromkeys(tokens))
        if tokens:
            for r in self.all_repos():
                r.resolve(tokens)

    def task(self, task_id):
        if self.agora_lookup is None:
            return None
        if task_id not in self._tasks:
            try:
                self._tasks[task_id] = self.agora_lookup(int(task_id))
            except Exception:  # noqa: BLE001 - the hub may be down: the other proofs still count
                self._tasks[task_id] = None
        return self._tasks[task_id]

    def cherry(self, token, primary):
        """A main commit that records « cherry picked from commit <token> » (the named repository first)."""
        for r in ([primary] if primary is not None else []) + [r for r in self.all_repos() if r is not primary]:
            hit = r.cherry_picked(token)
            if hit:
                return {'commit': hit[1], 'equivalent_of': hit[0], 'status': 'integrated', 'via': 'cherry_pick_trailer',
                        'repository': r.name, 'branch': r.branch, 'main_head': r.head}
        return None

    def imported(self, target, declared):
        """The code came in with an app folded into ``target``'s repository, whose history was not imported."""
        primary = self.repo(target) if target and target.get('subdir') else None
        imp = primary.import_of(target['subdir']) if primary is not None else None
        if not imp:
            return None
        if target.get('source_commit'):
            imp = {**imp, 'source_commit': target['source_commit']}
        return {'status': 'imported', 'reason': 'history_not_imported', 'repository': primary.name, 'branch': primary.branch,
                'import': imp, 'declared_commits': declared}

    def check(self, token, primary):
        """Proof for one declared commit id: in main, elsewhere in main, equivalent in main, or why not."""
        found = []
        if primary is not None:
            full = primary.resolve([token])[token]
            if full:
                found.append((primary, full))
        if not found:
            for r in self.all_repos():
                if r is not primary and r.resolve([token])[token]:
                    found.append((r, r.resolve([token])[token]))
        if not found:
            picked = self.cherry(token, primary)
            return picked or {'commit': token, 'status': 'unknown', 'reason': 'commit_not_found'}
        for r, full in found:
            if r.in_main(full) == 0:
                return {'commit': full, 'status': 'integrated', 'via': 'direct' if r is primary else 'other_repository',
                        'repository': r.name, 'branch': r.branch, 'main_head': r.head}
        picked = self.cherry(found[0][1], primary)
        if picked:
            return picked
        for r, full in found:
            for t in ([primary] if primary is not None and primary is not r else []) + [r]:
                eq = find_equivalent(r, full, t) if t.branch else None
                if eq:
                    out = {'commit': eq['commit'], 'equivalent_of': full, 'status': 'integrated', 'via': eq['method'],
                           'repository': t.name, 'branch': t.branch, 'main_head': t.head}
                    if r is not t:
                        out['original_repository'] = r.name
                    return out
        r, full = found[0]
        if not r.branch:
            return {'commit': full, 'status': 'unknown', 'reason': 'main_branch_not_found', 'repository': r.name}
        if r.in_main(full) is None:
            return {'commit': full, 'status': 'unknown', 'reason': 'ancestry_failed', 'repository': r.name}
        return {'commit': full, 'status': 'not_in_main', 'repository': r.name, 'branch': r.branch, 'main_head': r.head}

    def check_all(self, tokens, primary):
        per = [self.check(t, primary) for t in tokens]
        if all(p['status'] == 'integrated' for p in per):
            out = dict(per[0])
            out['via'] = _weakest([p['via'] for p in per])
        elif all(p['status'] in ('integrated', 'not_in_main') for p in per):
            out = dict(next(p for p in per if p['status'] == 'not_in_main'))
        else:
            out = dict(next(p for p in per if p['status'] == 'unknown'))
        if len(per) > 1:
            out['commits'] = per
        return out

    def agora_candidates(self, task_ids):
        """(task, way, ids, task repository name) the Ágora gives for where the work reached main, best first."""
        out = []
        for tid in task_ids:
            data = self.task(tid) or {}
            task, msgs = data.get('task') or {}, data.get('messages') or []
            for m in msgs:
                if m.get('kind') == 'resolution':
                    for hit in _INTEGRATED_AS.finditer(m.get('body') or ''):
                        out.append((tid, 'agora_resolution', split_commits(hit.group('ids')) or [], (hit.group('repo') or '').strip() or task.get('repo') or ''))
            last = [m for m in msgs if _COMMITS_LINE.search(m.get('body') or '')]
            if last:
                ids = split_commits(_COMMITS_LINE.findall(last[-1]['body'])[-1]) or []
                out.append((tid, 'agora_submission', ids, task.get('repo') or ''))
            ids = [c for c in (task.get('commits') or []) if isinstance(c, str)]
            out.append((tid, 'agora_task', split_commits(' '.join(ids)) or [], task.get('repo') or ''))
        return [c for c in out if c[2]]

    def agora_pairs(self, task_ids):
        """(task, old, new, repository name) from « old -> new » in the tasks' resolutions (a cherry-pick report)."""
        out = []
        for tid in task_ids:
            data = self.task(tid) or {}
            task, msgs = data.get('task') or {}, data.get('messages') or []
            for m in msgs:
                if m.get('kind') != 'resolution':
                    continue
                body = m.get('body') or ''
                spans = [(h.start(), h.end(), h.group('repo').strip()) for h in _REPO_LINE.finditer(body)]
                for p in _PAIR.finditer(body):
                    repo = next((name for a, b, name in spans if a <= p.start() < b), '') or task.get('repo') or ''
                    out.append((tid, p.group(1).lower(), p.group(2).lower(), repo))
                for h in _REPO_SHA.finditer(body):  # the id itself, now attributed to the repository the resolution names
                    out.append((tid, h.group('sha').lower(), h.group('sha').lower(), h.group('repo')))
        return out

    def closed_without_integration(self, task_ids):
        for tid in task_ids:
            for m in (self.task(tid) or {}).get('messages') or []:
                if m.get('kind') == 'resolution' and _NOT_INTEGRATED.search(m.get('body') or ''):
                    return {'status': 'not_in_main', 'reason': 'closed_without_integration', 'agora_task': tid,
                            'agora_note': ' '.join((m.get('body') or '').split())[:240]}
        return None

    def agora(self, task_ids, tokens):
        """Integration the Ágora records, proved by the named commit being in main. Skips a candidate that is only the
        declared commits again (those were already checked). An « old -> new » report maps each declared id; a new id
        that lives in an app folded without its history reads « imported ». A task closed without integrating says so."""
        closed = self.closed_without_integration(task_ids)
        if closed:
            return closed
        pairs = self.agora_pairs(task_ids)
        if tokens and pairs:
            per = []
            for t in tokens:
                hit = next((p for p in pairs if p[1].startswith(t) or t.startswith(p[1])), None)
                if hit is None:
                    break
                target = self.target(hit[3])
                res = self.check(hit[2], self.repo(target))
                if res['status'] != 'integrated':
                    res = self.imported(target, [t]) or res
                per.append({**res, 'agora_task': hit[0], 'declared': t})
            else:
                if all(p['status'] == 'integrated' for p in per):
                    return {**per[0], 'via': 'agora_resolution', 'proof_via': _weakest([p['via'] for p in per]),
                            'integrated_as': [p['commit'] for p in per], **({'commits': per} if len(per) > 1 else {})}
                if all(p['status'] in ('integrated', 'imported') for p in per):
                    return {**next(p for p in per if p['status'] == 'imported'), **({'commits': per} if len(per) > 1 else {})}
        for tid, way, ids, repo_name in self.agora_candidates(task_ids):
            if set(ids) <= set(tokens):
                continue
            res = self.check_all(ids, self.repo(self.target(repo_name)))
            if res['status'] == 'integrated' and res.get('via') in ('direct', 'other_repository', 'cherry_pick_trailer', 'patch_id', 'subject_date'):
                return {**res, 'via': way, 'proof_via': res['via'], 'agora_task': tid, 'integrated_as': ids}
        for tid in task_ids:
            # The task's own repository is an app folded into another without its history.
            target = self.target(((self.task(tid) or {}).get('task') or {}).get('repo'))
            res = self.imported(target, tokens) if target and target.get('subdir') else None
            if res:
                return {**res, 'agora_task': tid}
        return None


def agora_refs(delivery) -> list:
    """Ágora tasks behind a delivery: its own task, else the « #N » a tracker line cites (« ✅ hecho (#112, #113) »)."""
    if delivery.get('agora_task'):
        return [int(delivery['agora_task'])]
    declared = delivery.get('declared')
    if isinstance(declared, str):
        try:
            declared = json.loads(declared)
        except ValueError:
            declared = {'tracker_status': declared}
    declared = declared if isinstance(declared, dict) else {}
    return [int(n) for n in dict.fromkeys(_TASK_REF.findall(str(declared.get('tracker_status') or '')))]


def verify_deliveries(store, repo_roots, agora_lookup=None, ids=None):
    """Only inspect local repositories; never fetch or checkout.

    ``repo_roots`` maps each repository name a delivery may use to a path, or to {'path', 'subdir', 'name'} for an app
    folded into another repository, or {'search': True} for an old umbrella name (search every repository).
    ``agora_lookup(task_id)`` returns the hub's task document ({'task', 'messages'}) or None."""
    v = _Verifier(repo_roots, agora_lookup)
    rows = store.q('SELECT * FROM deliveries ORDER BY id')
    if ids is not None:  # only these deliveries (after one was corrected)
        wanted = {int(i) for i in ids}
        rows = [r for r in rows if r['id'] in wanted]
    plan = []
    for d in rows:
        target = v.target(d.get('repo')) or v.target(d.get('agora_space'))
        plan.append((d, target, split_commits(d.get('commit_sha'))))
    v.prefetch([t for _, _, tokens in plan for t in (tokens or [])])
    first = []
    for d, target, tokens in plan:
        try:
            primary = v.repo(target)
            if target and target.get('path') and primary is None:
                res = {'status': 'unknown', 'reason': 'repository_unavailable'}
            elif tokens is None:
                res = {'status': 'unknown', 'reason': 'invalid_commit_id', 'declared_commit': d.get('commit_sha')}
            elif not tokens:
                res = {'status': 'unknown', 'reason': 'no_commit_declared'}
            else:
                res = v.check_all(tokens, primary)
                if res.get('reason') == 'commit_not_found' and not target:
                    res['reason'] = 'repository_not_mapped'
        except subprocess.TimeoutExpired:
            res = {'status': 'unknown', 'reason': 'repository_unavailable'}
        first.append(res)
    # Second pass: what the Ágora says reached main, for whatever the declared ids could not prove.
    need = [i for i, r in enumerate(first) if r['status'] != 'integrated' and agora_refs(plan[i][0])]
    v.prefetch([t for i in need for c in v.agora_candidates(agora_refs(plan[i][0])) for t in c[2]]
               + [p[2] for i in need for p in v.agora_pairs(agora_refs(plan[i][0]))])
    results = []
    for i, (d, target, tokens) in enumerate(plan):
        res = first[i]
        refs = agora_refs(d)
        if i in need:
            try:
                alt = v.agora(refs, tokens or [])
            except subprocess.TimeoutExpired:
                alt = None
            if alt:
                res = {**alt, 'declared_commits': tokens or [], 'declared_result': {k: res.get(k) for k in ('status', 'reason') if res.get(k)}}
        if res['status'] == 'unknown' and target and target.get('subdir') and res.get('reason') in ('commit_not_found', 'repository_not_mapped'):
            res = v.imported(target, tokens or []) or res
        res = {'delivery_id': d['id'], 'commit': res.get('commit') or (tokens[0] if tokens else (d.get('commit_sha') or '')),
               **{k: val for k, val in res.items() if k != 'commit'}, 'functional_verification': 'unchanged'}
        if refs:
            res['agora_refs'] = refs
        _record(store, d, res, refs)
        results.append(res)
    return {'deliveries': results}


_VIA_NOTE = {'direct': '', 'other_repository': ' (found in another repository)', 'cherry_pick_trailer': ' (cherry-picked, the trailer names it)',
             'patch_id': ' (equivalent commit, same patch-id)',
             'subject_date': ' (equivalent commit, same subject and author date)', 'agora_resolution': ' (commit the Ágora resolution names)',
             'agora_submission': ' (commits of the last Ágora submission)', 'agora_task': ' (commits of the Ágora task)'}


def _record(store, delivery, result, refs):
    evidence = delivery.get('evidence') or {}
    if not isinstance(evidence, dict):
        evidence = {'original': evidence}
    evidence['commit_ancestry'] = result
    with store.tx() as connection:
        connection.execute('UPDATE deliveries SET evidence=? WHERE id=?', (json.dumps(evidence, ensure_ascii=False), delivery['id']))
        if not delivery.get('agora_task') and len(refs) == 1:
            # A tracker line that cites exactly one task: that task is the delivery's (unambiguous repair).
            connection.execute('UPDATE deliveries SET agora_task=? WHERE id=? AND agora_task IS NULL', (refs[0], delivery['id']))
    if result.get('reason') == 'closed_without_integration' and delivery['implementation'] == 'integrada':
        # The import read « done with commits » as integrated; the task's own resolution says it was closed without it.
        store.set_state('deliveries', delivery['id'], 'implementation', 'sin_implementar', by='ancestry',
                        note=f"Ágora task #{result.get('agora_task')} was closed without integrating; the commit is not in main")
    if result['status'] == 'integrated' and delivery['implementation'] != 'sustituida':
        # Superseded deliveries remain superseded even when their commit exists.
        note = 'Commit is in ' + str(result.get('branch')) + _VIA_NOTE.get(result.get('via') or 'direct', '') + '; functional verification unchanged'
        store.set_state('deliveries', delivery['id'], 'implementation', 'integrada', by='ancestry', note=note)
