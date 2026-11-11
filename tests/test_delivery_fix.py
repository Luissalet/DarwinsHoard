"""darwin_delivery_fix: correct the commit a delivery declared (history rewritten) and check it again, keeping what it declared."""
from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from darwin_hoard.config import Config
from darwin_hoard.main import create_app


def _git(root, *args):
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture
def client(tmp_path):
    repo = tmp_path / "Real Repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "-c", "user.name=F", "-c", "user.email=f@example.invalid", "commit", "--allow-empty", "-m", "Make the orb follow words")
    cfg = Config(data_dir=tmp_path / "data", port=5233, data_dir_configured=True, hub_url="http://127.0.0.1:9", hoards_root=tmp_path / "hoards")
    app = create_app(cfg, background=False)
    with TestClient(app, base_url="http://127.0.0.1:5233", client=("127.0.0.1", 50000)) as c:
        c.app.state.services.update_settings({"repo_aliases": {"Real Repo": {"path": str(repo)}}})
        c.repo, c.head = repo, _git(repo, "rev-parse", "HEAD")
        yield c


def _call(client, name, args):
    return client.post("/api/ui/call", json={"name": name, "arguments": args})


def test_a_lost_commit_is_replaced_by_the_one_in_main_and_the_old_one_is_kept(client):
    store = client.app.state.services.store
    did = store.upsert_delivery(key="k1", source_id=None, target="real", repo="Real Repo", commit_sha="a" * 12,
                                implementation="integrada", verification="documentada")
    assert _call(client, "darwin_verify_deliveries", {}).json()["summary"].get("unknown:commit_not_found") == 1
    r = client.post(f"/api/deliveries/{did}/fix", json={"commit_sha": client.head[:8], "note": "same subject in main", "by": "test"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["changed"] == ["commit_sha"] and out["status"] == "integrated" and out["implementation"] == "integrada"
    row = store.one("SELECT commit_sha, declared FROM deliveries WHERE id=?", (did,))
    assert row["commit_sha"] == client.head[:8] and row["declared"]["declared_before_fix"]["commit_sha"] == "a" * 12
    hist = [h for h in store.history_of("deliveries", did) if h["field"] == "commit_sha"]
    assert hist[-1]["old"] == "a" * 12 and hist[-1]["new"] == client.head[:8] and hist[-1]["note"] == "same subject in main"
    again = _call(client, "darwin_delivery_fix", {"id": did, "commit_sha": client.head[:8]}).json()
    assert again["changed"] == []


def test_clear_commit_and_bad_input(client):
    store = client.app.state.services.store
    did = store.upsert_delivery(key="k2", source_id=None, target="real", repo="Real Repo", commit_sha="b" * 12, agora_task=262,
                                implementation="sin_implementar")
    out = _call(client, "darwin_delivery_fix", {"id": did, "agora_task": 260, "clear_commit": True}).json()
    assert sorted(out["changed"]) == ["agora_task", "commit_sha"] and out["commit_sha"] is None and out["agora_task"] == 260
    assert out["reason"] == "no_commit_declared"
    assert _call(client, "darwin_delivery_fix", {"id": did}).status_code == 400
    assert _call(client, "darwin_delivery_fix", {"id": did, "commit_sha": "not a sha"}).status_code == 400
    assert _call(client, "darwin_delivery_fix", {"id": did, "commit_sha": "abc1234", "clear_commit": True}).status_code == 400
    assert _call(client, "darwin_delivery_fix", {"id": 99999, "commit_sha": "abc1234"}).status_code == 404


def test_only_the_corrected_delivery_is_checked_again(client):
    store = client.app.state.services.store
    one = store.upsert_delivery(key="k3", source_id=None, target="real", repo="Real Repo", commit_sha="c" * 12)
    two = store.upsert_delivery(key="k4", source_id=None, target="real", repo="Real Repo", commit_sha=client.head)
    out = _call(client, "darwin_delivery_fix", {"id": one, "note": "same", "repo": "Real Repo", "agora_task": 5}).json()
    assert out["checked"] == 1
    assert store.one("SELECT evidence FROM deliveries WHERE id=?", (two,))["evidence"].get("commit_ancestry") is None
