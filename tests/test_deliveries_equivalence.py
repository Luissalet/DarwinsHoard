"""Deliveries whose commit was rewritten, lives in another repository, or came in with an app folded into another."""
import json
import subprocess

from darwin_hoard.repo_map import RepoMap, norm, provenance_commit
from darwin_hoard.store import Store
from darwin_ingest import verify_deliveries
from darwin_ingest.deliveries import split_commits


def _repo(path):
    path.mkdir(parents=True)

    def git(*args):
        r = subprocess.run(['git', '-C', str(path), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', *args],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()

    git('init', '-q', '-b', 'main')
    return git


def _commit(git, root, name, text, msg, date=None):
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(text, encoding='utf-8')
    git('add', name)
    args = ['commit', '-q', '-m', msg] + (['--date', date] if date else [])
    git(*args)
    return git('rev-parse', 'HEAD')


def _deliver(store, key, repo, sha, **kw):
    return store.upsert_delivery(key=key, source_id=None, target='x', repo=repo, commit_sha=sha, implementation='sin_implementar', **kw)


def test_rewritten_history_finds_the_equivalent_commit(tmp_path):
    root = tmp_path / 'r'
    git = _repo(root)
    _commit(git, root, 'base.txt', 'base\n', 'Base')
    # 1) a branch commit rebased onto a newer main (new sha, same patch, same author date)
    git('checkout', '-q', '-b', 'feature')
    rebased_away = _commit(git, root, 'feature.txt', 'feature\n', 'Add the feature', date='2026-10-01T10:00:00')
    git('checkout', '-q', 'main')
    _commit(git, root, 'other.txt', 'other\n', 'Unrelated work')
    git('cherry-pick', rebased_away)
    picked = git('rev-parse', 'HEAD')
    # 2) a main commit whose message was rewritten afterwards (amend = history rewrite; the old object stays unreachable)
    reworded = _commit(git, root, 'reword.txt', 'r\n', 'Message with a trailer to drop')
    git('commit', '-q', '--amend', '-m', 'Message without the trailer')
    rewritten = git('rev-parse', 'HEAD')
    git('branch', '-D', 'feature')
    assert reworded != rewritten and rebased_away != picked
    store = Store(tmp_path / 'd.db')
    a = _deliver(store, 'a', 'R', rebased_away[:8])
    b = _deliver(store, 'b', 'R', reworded)
    res = {r['delivery_id']: r for r in verify_deliveries(store, {'R': str(root)})['deliveries']}
    assert res[a]['status'] == 'integrated' and res[a]['via'] == 'patch_id'
    assert res[a]['commit'] == picked and res[a]['equivalent_of'] == rebased_away
    assert res[b]['status'] == 'integrated' and res[b]['via'] == 'patch_id' and res[b]['commit'] == rewritten
    row = store.one('SELECT * FROM deliveries WHERE id=?', (a,))
    assert row['implementation'] == 'integrada' and row['evidence']['commit_ancestry']['equivalent_of'] == rebased_away
    store.close()


def test_branch_commit_without_equivalent_stays_not_in_main(tmp_path):
    root = tmp_path / 'r'
    git = _repo(root)
    _commit(git, root, 'base.txt', 'base\n', 'Base')
    git('checkout', '-q', '-b', 'side')
    side = _commit(git, root, 'side.txt', 'side\n', 'Only on a branch')
    store = Store(tmp_path / 'd.db')
    d = _deliver(store, 'a', 'R', side)
    [r] = verify_deliveries(store, {'R': str(root)})['deliveries']
    assert r['delivery_id'] == d and r['status'] == 'not_in_main' and 'via' not in r
    store.close()


def test_other_repository_multi_ids_and_garbage(tmp_path):
    ra, rb = tmp_path / 'a', tmp_path / 'b'
    ga, gb = _repo(ra), _repo(rb)
    in_a = _commit(ga, ra, 'a.txt', 'a\n', 'In A')
    in_b = _commit(gb, rb, 'b.txt', 'b\n', 'In B')
    store = Store(tmp_path / 'd.db')
    elsewhere = _deliver(store, 'e', 'A', in_b[:9])           # declared in A, lives in B (multi-repository task)
    umbrella = _deliver(store, 'u', 'LocalAI', in_a[:7])      # old umbrella name: searched everywhere
    both = _deliver(store, 'm', 'A', f'{in_a[:7]} {in_b[:7]}')  # several ids in one field
    garbage = _deliver(store, 'g', 'A', 'see the thread')
    unmapped = _deliver(store, 'n', 'Nowhere', 'abcdef1234')
    roots = {'A': str(ra), 'B': str(rb), 'LocalAI': {'search': True}}
    res = {r['delivery_id']: r for r in verify_deliveries(store, roots)['deliveries']}
    assert res[elsewhere]['status'] == 'integrated' and res[elsewhere]['via'] == 'other_repository' and res[elsewhere]['repository'] == 'B'
    assert res[umbrella]['status'] == 'integrated' and res[umbrella]['repository'] == 'A'
    assert res[both]['status'] == 'integrated' and len(res[both]['commits']) == 2 and res[both]['via'] == 'other_repository'
    assert res[garbage]['reason'] == 'invalid_commit_id' and res[garbage]['declared_commit'] == 'see the thread'
    assert res[unmapped]['reason'] == 'repository_not_mapped'
    store.close()


def test_split_commits():
    assert split_commits('7cc2354 5e8241b') == ['7cc2354', '5e8241b']
    assert split_commits('a1b2c3d, A1B2C3D + 0123456') == ['a1b2c3d', '0123456']
    assert split_commits('') == [] and split_commits(None) == []
    assert split_commits('sin-commit') is None


def test_gone_commit_uses_what_the_agora_says_reached_main(tmp_path):
    root = tmp_path / 'r'
    git = _repo(root)
    landed = _commit(git, root, 'f.txt', '1\n', 'Integrated work')
    tasks = {
        7: {'task': {'repo': 'R', 'commits': ['deadbeef1']},
            'messages': [{'kind': 'proposal', 'body': 'r2\n\nSubmission revision: 2\nCommits: deadbeef1'},
                         {'kind': 'resolution', 'body': f'Integrado en master ({landed[:8]}). 357 pruebas.'}]},
        8: {'task': {'repo': 'R', 'commits': ['cafebabe1']},
            'messages': [{'kind': 'proposal', 'body': f'Submission revision: 3\nCommits: {landed[:10]}'}]},
        9: {'task': {'repo': 'R', 'commits': [landed[:8]]}, 'messages': []},
    }
    store = Store(tmp_path / 'd.db')
    by_resolution = _deliver(store, 'a', 'R', 'deadbeef1', agora_task=7)
    by_submission = _deliver(store, 'b', 'R', 'cafebabe1', agora_task=8)
    tracker = store.upsert_delivery(key='c', source_id=None, target='x', repo='R', commit_sha='', implementation='integrada',
                                    declared={'tracker_status': '✅ hecho (#9)'})
    nothing = _deliver(store, 'd', 'R', 'feedface1')
    res = {r['delivery_id']: r for r in verify_deliveries(store, {'R': str(root)}, agora_lookup=tasks.get)['deliveries']}
    assert res[by_resolution]['via'] == 'agora_resolution' and res[by_resolution]['commit'] == landed
    assert res[by_resolution]['declared_result'] == {'status': 'unknown', 'reason': 'commit_not_found'}
    assert res[by_submission]['via'] == 'agora_submission' and res[by_submission]['agora_task'] == 8
    assert res[tracker]['via'] == 'agora_task' and res[tracker]['agora_refs'] == [9]
    assert store.one('SELECT agora_task FROM deliveries WHERE id=?', (tracker,))['agora_task'] == 9  # unambiguous repair
    assert res[nothing]['status'] == 'unknown' and res[nothing]['reason'] == 'commit_not_found'
    # without the hub the same deliveries are honestly unknown
    res = {r['delivery_id']: r for r in verify_deliveries(store, {'R': str(root)})['deliveries']}
    assert res[by_resolution]['reason'] == 'commit_not_found' and res[tracker]['reason'] == 'no_commit_declared'
    store.close()


def test_folded_app_reads_imported_with_its_import_commit(tmp_path):
    host = tmp_path / 'Pygmalion'
    git = _repo(host)
    _commit(git, host, 'pygmalion/app.py', 'x = 1\n', 'Start')
    imported = _commit(git, host, 'galton_hoard/bench.py', 'y = 2\n', 'Fold the bench app in')
    (host / 'provenance' / 'galton').mkdir(parents=True)
    (host / 'provenance' / 'galton' / 'source.json').write_text(json.dumps({'repository': 'https://github.com/u/GaltonsHoard', 'commit': 'abc1234def'}))
    rmap = RepoMap(hub_repos={"Pygmalion's Hoard": str(host)})
    roots = rmap.roots(["Galton's Hoard"])
    assert roots["Galton's Hoard"]['subdir'] == 'galton_hoard' and roots["Galton's Hoard"]['source_commit'] == 'abc1234def'
    store = Store(tmp_path / 'd.db')
    d = _deliver(store, 'g', "Galton's Hoard", 'a92b7e0')
    [r] = verify_deliveries(store, roots)['deliveries']
    assert r['delivery_id'] == d and r['status'] == 'imported' and r['reason'] == 'history_not_imported'
    assert r['import']['commit'] == imported and r['import']['source_commit'] == 'abc1234def' and r['repository'] == "Pygmalion's Hoard"
    assert store.one('SELECT implementation FROM deliveries WHERE id=?', (d,))['implementation'] == 'sin_implementar'
    store.close()


def test_repo_map_aliases_settings_spaces_and_unknown(tmp_path):
    hub_dir, ws = tmp_path / 'Hoard Hub', tmp_path / 'game'
    _repo(hub_dir), _repo(ws)
    rmap = RepoMap(hub_repos={'Hoard Hub': str(hub_dir)}, spaces={'blood-arrows': str(ws), 'ecosystem': str(tmp_path)},
                   custom={'Old Thing': 'Hoard Hub', 'HoardLink': {'path': str(ws)}})
    assert rmap.resolve('HoardLink')['path'] == str(ws)              # Luis's entry wins over the built-in one
    assert rmap.resolve('old thing')['path'] == str(hub_dir)         # case and punctuation do not matter
    assert rmap.resolve('BloodArrows')['path'] == str(ws)            # alias to an Ágora space's workspace
    assert rmap.resolve('LocalAI') == {'search': True, 'name': 'LocalAI', 'via': 'builtin'}
    assert rmap.resolve('Never Heard Of') is None
    roots = rmap.roots(['HoardLink', 'LocalAI', 'Never Heard Of'])
    assert 'ecosystem' not in roots and roots['LocalAI']['search'] and 'Never Heard Of' not in roots
    rows = {r['name']: r for r in rmap.table({'HoardLink': 3})}
    assert rows['HoardLink']['origin'] == 'settings' and rows['HoardLink']['deliveries'] == 3 and rows['HoardLink']['ok']
    assert norm("Galton's Hoard") == norm('GaltonsHoard') == norm('galton hoard')
    assert provenance_commit(str(tmp_path / 'missing'), 'X') == ''


def test_cherry_pick_trailer_and_agora_old_to_new_report(tmp_path):
    root, host = tmp_path / 'r', tmp_path / 'host'
    git, ghost = _repo(root), _repo(host)
    gone = 'c6d2ec447974c7b2e5a5d27eb15a8760c46510c7'
    picked = _commit(git, root, 'a.txt', 'a\n', f'Explain a feature\n\n(cherry picked from commit {gone})')
    moved = _commit(git, root, 'b.txt', 'b\n', 'Browser lanes')
    ff = _commit(git, root, 'c.txt', 'c\n', 'Graphic shots')
    _commit(ghost, host, 'tantalus_hoard/x.py', '1\n', 'Fold the watcher in')
    tasks = {
        265: {'task': {'repo': 'R', 'commits': []}, 'messages': [{'kind': 'resolution', 'body':
              f'Integrado por cherry-pick -x:\n- R main: 72a6658c -> {moved}\n- Tantalus\'s Hoard main: b74366a3 -> 006d8e4c\n'}]},
        120: {'task': {'repo': 'R', 'commits': ['e7c8e46']}, 'messages': [{'kind': 'resolution', 'body': f'Integrada en R main {ff[:7]} (ff desde 82f8052).'}]},
    }
    roots = {'R': str(root), "Hermes's Hoard": str(host), "Tantalus's Hoard": {'path': str(host), 'subdir': 'tantalus_hoard'}}
    store = Store(tmp_path / 'd.db')
    t = _deliver(store, 't', 'R', gone[:8])
    lanes = _deliver(store, 'l', 'R', '72a6658cf4f857b3e33b2893071da44889324b47', agora_task=265)
    folded = _deliver(store, 'f', 'R', 'b74366a3565b6e413989f886329f4fd1d7e3eddf', agora_task=265)
    shots = _deliver(store, 's', 'R', 'e7c8e46', agora_task=120)
    res = {r['delivery_id']: r for r in verify_deliveries(store, roots, agora_lookup=tasks.get)['deliveries']}
    assert res[t]['via'] == 'cherry_pick_trailer' and res[t]['commit'] == picked and res[t]['equivalent_of'] == gone
    assert res[lanes]['via'] == 'agora_resolution' and res[lanes]['commit'] == moved
    assert res[folded]['status'] == 'imported' and res[folded]['import']['subdir'] == 'tantalus_hoard' and res[folded]['agora_task'] == 265
    assert res[shots]['via'] == 'agora_resolution' and res[shots]['commit'] == ff
    store.close()


def test_resolution_names_repositories_and_closed_without_integration(tmp_path):
    root, host = tmp_path / 'r', tmp_path / 'host'
    git, ghost = _repo(root), _repo(host)
    hub_commit = _commit(git, root, 'a.txt', 'a\n', 'Fleet watcher')
    _commit(ghost, host, 'tantalus_hoard/x.py', '1\n', 'Fold the watcher in')
    rmap = RepoMap(hub_repos={'Hoard Hub': str(root), "Hermes's Hoard": str(host)})
    tasks = {
        262: {'task': {'repo': 'LocalAI', 'commits': []}, 'messages': [{'kind': 'resolution', 'body':
              f'Integrado: HoardLink main {hub_commit[:7]}, Tantalus main 57da1e2 y Faustus master dae07fc7 (106 pruebas).'}]},
        283: {'task': {'repo': 'Hoard Hub', 'commits': []}, 'messages': [{'kind': 'resolution', 'body': 'Cierre sin integrar (prioridad de Luis).'}]},
    }
    store = Store(tmp_path / 'd.db')
    tant = _deliver(store, 't', 'LocalAI', '57da1e2', agora_task=262)
    other = _deliver(store, 'o', 'LocalAI', 'da25171', agora_task=262)
    closed = store.upsert_delivery(key='c', source_id=None, target='x', repo='Hoard Hub', commit_sha='b193c405', implementation='integrada', agora_task=283)
    res = {r['delivery_id']: r for r in verify_deliveries(store, rmap.roots(['LocalAI', 'Hoard Hub']), agora_lookup=tasks.get)['deliveries']}
    assert res[tant]['status'] == 'imported' and res[tant]['import']['subdir'] == 'tantalus_hoard'
    assert res[other]['status'] == 'unknown' and res[other]['reason'] == 'commit_not_found'  # the resolution does not name it
    assert res[closed]['status'] == 'not_in_main' and res[closed]['reason'] == 'closed_without_integration'
    assert store.one('SELECT implementation FROM deliveries WHERE id=?', (closed,))['implementation'] == 'sin_implementar'
    store.close()
