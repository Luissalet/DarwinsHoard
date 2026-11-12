from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from darwin_hoard import skill_impacts
from darwin_hoard.config import Config
from darwin_hoard.errors import DarwinError
from darwin_hoard.main import create_app
from darwin_hoard.services import Services
from darwin_hoard.store import Store
from darwin_hoard.agent_tools import call_tool


def fixture(tmp_path):
    lib = tmp_path / 'library'
    for slug, apps in [('image-editing', 'photos'), ('image-unrelated', 'other')]:
        path = lib / slug / 'SKILL.md'
        path.parent.mkdir(parents=True)
        path.write_text(f'''---
name: {slug}
description: Edit images with layers and preserve originals. Use when image editing is requested.
version: 1.0
apps: [{apps}]
tags: [image, editing, layers]
---
## When to Use
When editing an image.
## Procedure
1. Preserve original layers.
2. Edit the image.
## Verification
The original and edited image exist.
''', encoding='utf-8')
    config = Config(data_dir=tmp_path / 'data', faustus_dir=lib, hub_url='http://127.0.0.1:1')
    store = Store(config.db_path)
    sid = store.upsert_source(repo='sample/image-editing', title='image editing layers', legacy_radar_no=1200)
    did = store.upsert_delivery(key='delivery', source_id=sid, target='photos', commit_sha='a' * 40,
                                repo='Photo Hoard', implementation='integrada', evidence={'commit_ancestry': {'status': 'integrated'}})
    return store, config, sid, did


def test_candidates_are_target_specific_and_documented_links_preserve_proof(tmp_path):
    store, config, sid, did = fixture(tmp_path)
    report = skill_impacts.report(store, config)
    item = report['items'][0]
    assert item['status'] == 'suggested' and item['skills'] == []
    assert [r['slug'] for r in item['suggestions']] == ['image-editing']
    assert item['suggestions'][0]['on_shelf'] is None
    assert skill_impacts.report(store, config, shelves={'photos': []})['items'][0]['suggestions'] == []
    skill_impacts.link(store, config, delivery_id=did, slug='image-editing', reason='Adds editable layers to the image procedure.')
    row = skill_impacts.report(store, config, source_id=sid, shelves={'photos': ['image-editing']})['items'][0]
    assert row['status'] == 'documented' and row['commit_ancestry']['status'] == 'integrated'
    assert row['skills'][0]['on_shelf'] is True and row['skills'][0]['source_changed'] is False
    path = config.faustus_dir / 'image-editing' / 'SKILL.md'
    path.write_text(path.read_text(encoding='utf-8').replace('1.0', '1.1'), encoding='utf-8')
    assert skill_impacts.report(store, config)['items'][0]['skills'][0]['source_changed'] is True
    skill_impacts.link(store, config, delivery_id=did, slug='image-editing', on=False)
    assert store.one('SELECT evidence FROM deliveries WHERE id=?', (did,))['evidence']['commit_ancestry']['status'] == 'integrated'
    assert skill_impacts.report(store, config)['items'][0]['skills'] == []


def test_missing_library_and_pagination_keep_every_integrated_repo(tmp_path, monkeypatch):
    store, config, sid, did = fixture(tmp_path)
    skill_impacts.link(store, config, delivery_id=did, slug='image-editing', reason='Editable layers.')
    for n in range(3):
        store.upsert_delivery(key=f'next{n}', source_id=sid, target='unknown', implementation='integrada')
    store.upsert_delivery(key='pending', source_id=sid, target='photos')
    monkeypatch.setattr(skill_impacts, 'library', lambda config: [])
    first = skill_impacts.report(store, config, limit=2)
    second = skill_impacts.report(store, config, limit=2, offset=2)
    assert first['total'] == 4 and len(first['items']) == 2
    assert len({r['delivery_id'] for r in first['items'] + second['items']}) == 4
    documented = next(r for r in second['items'] if r['delivery_id'] == did)
    assert documented['skills'][0]['available'] is False
    assert not first['library_available']
    assert skill_impacts.report(store, config, target='no-app')['items'] == []


def test_links_validate_source_and_reason_without_editing_skills(tmp_path):
    store, config, _, did = fixture(tmp_path)
    before = skill_impacts.read(config, 'image-editing')['text']
    with pytest.raises(DarwinError):
        skill_impacts.link(store, config, delivery_id=did, slug='missing', reason='A reason')
    with pytest.raises(DarwinError):
        skill_impacts.link(store, config, delivery_id=did, slug='image-editing')
    with pytest.raises(DarwinError):
        skill_impacts.link(store, config, delivery_id=9999, slug='image-editing', reason='A reason')
    assert skill_impacts.read(config, 'image-editing')['text'] == before


def test_agent_pagination_keeps_the_entire_requested_page(tmp_path, monkeypatch):
    store, config, sid, _ = fixture(tmp_path)
    for n in range(80):
        store.upsert_delivery(key=f'large{n}', source_id=sid, target='photos', implementation='integrada',
                              declared={'what': 'image editing layers ' * 30})
    store.close()
    service = Services(config)
    monkeypatch.setattr('darwin_hoard.tree._get', lambda *a, **k: {})
    result = call_tool(service, 'darwin_skill_impacts', {'limit': 80})
    assert len(result['items']) == 80 and result['total'] == 81
    assert 'truncated' not in result


def test_http_and_agent_genealogy_and_radar_share_links(tmp_path, monkeypatch):
    store, config, sid, did = fixture(tmp_path)
    store.close()
    services = Services(config)
    monkeypatch.setattr('darwin_hoard.tree._get', lambda *a, **k: {'ok': True, 'apps': [{'id': 'photos', 'skills': ['image-editing']}]})
    with TestClient(create_app(config, services=services, background=False), base_url='http://127.0.0.1:5233', client=('127.0.0.1', 50000)) as client:
        reply = client.post('/api/skill-impacts/link', json={'delivery_id': did, 'slug': 'image-editing', 'reason': 'Keeps editable layers.'})
        assert reply.status_code == 200
        assert client.get('/api/skill-impacts').json()['items'][0]['skills'][0]['slug'] == 'image-editing'
        assert 'Procedure' in client.get('/api/skill-impacts/skill?slug=image-editing').json()['text']
        source = client.get(f'/api/discoveries/{sid}').json()
        assert source['skill_impacts']['items'][0]['status'] == 'documented'
        radar = client.get('/api/radar/plan').json()
        assert radar['implemented_skill_impacts']['items'][0]['skills'][0]['slug'] == 'image-editing'
        assert client.get('/skill-impacts.js').status_code == 200
