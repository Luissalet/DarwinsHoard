import subprocess
from darwin_hoard.store import Store
from darwin_ingest import verify_deliveries


def test_ancestry_does_not_certify_function_or_change_superseded(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    def git(*args):
        r = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()
    git('init', '-b', 'main')
    git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--allow-empty', '-m', 'base')
    main = git('rev-parse', 'HEAD')
    git('checkout', '-b', 'candidate')
    git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--allow-empty', '-m', 'candidate')
    candidate = git('rev-parse', 'HEAD')
    store = Store(tmp_path / 'test.db')
    for key, sha, state in [('main', main, 'parcial'), ('branch', candidate, 'sin_implementar'), ('gone', 'f' * 40, 'sin_implementar'), ('superseded', main, 'sustituida')]:
        store.upsert_delivery(key=key, source_id=None, target='sample', repo='sample', commit_sha=sha, implementation=state, verification='desconocida')
    result = verify_deliveries(store, {'sample': root})
    assert [r['status'] for r in result['deliveries']] == ['integrated', 'not_in_main', 'unknown', 'integrated']
    rows = store.q('SELECT * FROM deliveries ORDER BY id')
    assert [r['implementation'] for r in rows] == ['integrada', 'sin_implementar', 'sin_implementar', 'sustituida']
    assert all(r['verification'] == 'desconocida' for r in rows)
    assert rows[1]['evidence']['commit_ancestry']['main_head'] == main
    store.close()
