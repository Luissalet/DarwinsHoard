from __future__ import annotations

import hashlib
import json

from darwin_hoard.canon import extract_refs


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def ingest_batch(store, records, *, channel='manual'):
    """Caller supplies stable occurrence keys. Replay also repairs unfinished links."""
    result = {'created': 0, 'existing': 0, 'captures': [], 'sources': []}
    for record in records:
        key = record.get('capture_key')
        if not isinstance(key, str) or not key:
            raise ValueError('Each capture needs a stable capture_key')
        cid, created = store.add_capture(
            capture_key=key, channel=channel, text=record.get('text') or '',
            at=record.get('at'), chat=record.get('chat') or '', author=record.get('author') or '',
            attachment=record.get('attachment') or '', provenance=record.get('provenance') or {},
            declared=record.get('declared') or {}, url=record.get('url') or '')
        result['created' if created else 'existing'] += 1
        result['captures'].append(cid)
        text = (record.get('text') or '') + '\n' + (record.get('url') or '')
        for ref in extract_refs(text):
            existing = store.source_by_key(ref['key'])
            sid = existing['id'] if existing else store.upsert_source(url=ref['url'], meta={'identity_evidence': 'candidate' if ref['kind'] == 'candidate' else 'url', 'github_verified': False})
            store.link_capture(cid, sid)
            result['sources'].append(sid)
    result['sources'] = sorted(set(result['sources']))
    return result


def sync_whatsapp_page(store, client, *, account, chat, limit=200):
    """One resumable pass step. Client is a read-only message-page callable.

    A completed pass resets its cursor: the next pass discovers edits/late rows.
    Store writes precede cursor advance, so retries use stable revision keys.
    """
    if not isinstance(account, str) or not account or not isinstance(chat, str) or '@' not in chat:
        raise ValueError('account and exact chat JID are required')
    state_key = 'whatsapp-pass:' + _digest([account, chat])
    state = store.get_meta(state_key, {})
    cursor = state.get('cursor') or ''
    page = client(chat=chat, cursor=cursor, limit=limit)
    if not isinstance(page, dict) or not isinstance(page.get('messages'), list) or type(page.get('has_more')) is not bool:
        raise ValueError('Invalid message-page response')
    next_cursor = page.get('next_cursor')
    if page['has_more'] and (not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor):
        raise ValueError('Message page did not advance its cursor')
    records = []
    for message in page['messages']:
        if message.get('chat') != chat or not isinstance(message.get('id'), str) or not message['id']:
            raise ValueError('Page contains a message without an ID or from another chat')
        content = {k: message.get(k) for k in ('text', 'kind', 'media', 'attachment', 'edited', 'deleted', 'reply_to')}
        records.append({
            'capture_key': 'whatsapp:' + _digest([account, chat, message['id'], content]),
            'text': message.get('text') or '', 'at': message.get('ts'), 'chat': chat,
            'author': message.get('from') or ('me' if message.get('from_me') else ''),
            'attachment': json.dumps(message.get('media') or message.get('attachment') or '', ensure_ascii=False),
            'provenance': {'account': account, 'chat': chat, 'message_id': message['id'], 'revision': _digest(content), 'from_me': bool(message.get('from_me'))},
            'declared': {'edited': bool(message.get('edited')), 'deleted': bool(message.get('deleted')), 'coverage': page.get('coverage')},
        })
    result = ingest_batch(store, records, channel='whatsapp')
    coverage = page.get('coverage') or {'scope': 'unknown', 'phone_history_complete': False}
    store.set_meta(state_key, {'cursor': next_cursor if page['has_more'] else '', 'coverage': coverage})
    return {**result, 'has_more': page['has_more'], 'next_cursor': next_cursor, 'coverage': coverage, 'pass_complete': not page['has_more']}
