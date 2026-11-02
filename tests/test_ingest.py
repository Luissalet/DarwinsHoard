import pytest
from darwin_hoard.store import Store
from darwin_ingest import ingest_batch, sync_whatsapp_page


def message(mid='m1', text='https://github.com/example/research'):
    return {'id': mid, 'chat': 'gittrend@g.us', 'ts': 10, 'text': text, 'from_me': True}


def test_replay_edits_own_messages_and_multiple_sources(tmp_path):
    store = Store(tmp_path / 'test.db')
    rows = [message(text='a' * 9000 + ' https://github.com/example/one https://github.com/example/two')]
    def client(**kw):
        return {'messages': rows, 'next_cursor': 'end', 'has_more': False, 'coverage': {'phone_history_complete': False}}
    args = dict(account='personal', chat='gittrend@g.us')
    assert sync_whatsapp_page(store, client, **args)['created'] == 1
    assert sync_whatsapp_page(store, client, **args)['existing'] == 1
    assert store.counts()['sources'] == 2
    assert len(store.q('SELECT * FROM captures')[0]['text']) > 9000
    rows[0]['text'] = 'edited'
    rows[0]['edited'] = True
    rows.append(message('late', 'late arrival'))
    assert sync_whatsapp_page(store, client, **args)['created'] == 2
    assert store.counts()['captures'] == 3
    assert store.q('SELECT * FROM captures')[0]['provenance']['from_me'] is True
    store.close()


def test_failure_before_cursor_commit_replays_without_duplicates(tmp_path, monkeypatch):
    path = tmp_path / 'test.db'
    store = Store(path)
    original = store.set_meta
    monkeypatch.setattr(store, 'set_meta', lambda *a: (_ for _ in ()).throw(RuntimeError('power cut')))
    calls = []
    def client(**kw):
        calls.append(kw['cursor'])
        return {'messages': [message()], 'next_cursor': 'next', 'has_more': True}
    with pytest.raises(RuntimeError):
        sync_whatsapp_page(store, client, account='a', chat='gittrend@g.us')
    store.close()
    store = Store(path)
    assert sync_whatsapp_page(store, client, account='a', chat='gittrend@g.us')['existing'] == 1
    assert calls == ['', '']
    assert store.counts()['captures'] == 1
    store.close()


def test_cross_chat_and_nonadvancing_page_do_not_advance(tmp_path):
    store = Store(tmp_path / 'test.db')
    for page in [
        {'messages': [{**message(), 'chat': 'private@g.us'}], 'next_cursor': 'x', 'has_more': True},
        {'messages': [], 'next_cursor': '', 'has_more': True},
    ]:
        with pytest.raises(ValueError):
            sync_whatsapp_page(store, lambda **kw: page, account='a', chat='gittrend@g.us')
    assert store.counts()['captures'] == 0
    assert store.q('SELECT * FROM meta') == []
    store.close()


def test_generic_ingestion_preserves_two_occurrences_one_source(tmp_path):
    store = Store(tmp_path / 'test.db')
    store.upsert_source(url='https://github.com/example/project', meta={'github_verified': True})
    records = [{'capture_key': str(i), 'url': 'https://github.com/example/project'} for i in range(2)]
    assert ingest_batch(store, records, channel='links')['created'] == 2
    assert ingest_batch(store, records, channel='links')['existing'] == 2
    assert store.counts()['sources'] == 1
    assert store.counts()['captures'] == 2
    assert store.q('SELECT * FROM sources')[0]['meta']['github_verified'] is True
    store.close()
