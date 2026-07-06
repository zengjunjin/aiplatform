"""Phase 6 SSE chat acceptance test.

Tests the full chat flow:
1. Create a chat session bound to the test KB
2. Send a message and consume the SSE stream
3. Verify events: searching, delta (tokens), done (references)
4. Verify assistant message was persisted to PG
5. Verify message history
"""
import json
import time
import requests

BASE = 'http://localhost:8000'
result = {'phase': 6, 'steps': []}


def add(name, ok, **kwargs):
    d = {'name': name, 'ok': ok}
    d.update(kwargs)
    result['steps'].append(d)


def main():
    # 1. login
    r = requests.post(BASE + '/api/v1/auth/login',
                      json={'username':'admin','password':'admin123'})
    token = r.json().get('data', {}).get('access_token', '')
    add('login', bool(token))
    headers = {'Authorization': 'Bearer ' + token}

    # 2. KB
    r = requests.get(BASE + '/api/v1/knowledge-bases', headers=headers)
    kbs = r.json().get('data', [])
    kb_id = kbs[0]['id'] if kbs else None
    add('kb', kb_id is not None, kb_id=kb_id)
    if not kb_id:
        return

    # 3. create chat session
    r = requests.post(BASE + '/api/v1/chat/sessions',
                      json={'kb_id': kb_id, 'title': 'Phase 6 Test Session'},
                      headers=headers)
    sess_data = r.json().get('data', {})
    session_id = sess_data.get('id')
    add('create_session', session_id is not None,
        session_id=session_id, status=r.status_code)
    if not session_id:
        return

    # 4. send message + consume SSE stream
    try:
        t0 = time.time()
        r = requests.post(
            BASE + '/api/v1/chat/sessions/' + str(session_id) + '/messages',
            json={'content': 'What is FastAPI?'},
            headers=headers,
            stream=True,
            timeout=300,
        )
        add('sse_status', r.status_code == 200, status=r.status_code)

        events = []
        delta_count = 0
        full_text = ''
        references = []
        done_event = None
        search_event = None

        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith('data: '):
                payload = line[6:]
                try:
                    evt = json.loads(payload)
                    events.append(evt)
                    ev_type = evt.get('event')
                    if ev_type == 'searching':
                        search_event = evt
                    elif ev_type == 'delta':
                        delta_count += 1
                        full_text += evt.get('content', '')
                    elif ev_type == 'done':
                        done_event = evt
                        references = evt.get('references', [])
                    elif ev_type == 'error':
                        add('sse_error', False, error=evt.get('message'))
                except json.JSONDecodeError:
                    continue
        elapsed = time.time() - t0
        add('sse_stream',
            delta_count > 0 and len(full_text) > 10,
            delta_count=delta_count,
            total_chars=len(full_text),
            time_s=round(elapsed, 2),
            answer_preview=full_text[:100])
        if search_event:
            add('sse_search_event', True,
                chunks_found=search_event.get('chunks_found'))
        if done_event:
            add('sse_done_event', True,
                refs_count=len(references))
    except Exception as e:
        add('sse_stream', False, error=str(e)[:200])
        return

    # 5. Verify message persisted
    time.sleep(1)
    r = requests.get(BASE + '/api/v1/chat/sessions/' + str(session_id),
                      headers=headers)
    sess_data = r.json().get('data', {})
    messages = sess_data.get('messages', [])
    add('messages_persisted',
        len(messages) >= 2,
        message_count=len(messages))
    if len(messages) >= 2:
        assistant_msg = messages[-1]
        add('assistant_message',
            assistant_msg.get('role') == 'assistant',
            role=assistant_msg.get('role'),
            content_len=len(assistant_msg.get('content', '')),
            has_refs=bool(assistant_msg.get('referenced_chunks')))

    # 6. List sessions
    r = requests.get(BASE + '/api/v1/chat/sessions', headers=headers)
    sessions = r.json().get('data', [])
    add('list_sessions',
        any(s.get('id') == session_id for s in sessions),
        total_sessions=len(sessions))

    # 7. Delete session
    r = requests.delete(BASE + '/api/v1/chat/sessions/' + str(session_id),
                         headers=headers)
    add('delete_session', r.status_code == 200, status=r.status_code)

    # Save
    with open(r'G:\aiplatform\backend\phase6_result.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    passed = sum(1 for s in result['steps'] if s['ok'])
    total = len(result['steps'])
    print('Result: ' + str(passed) + '/' + str(total) + ' PASS')
    for s in result['steps']:
        status = 'PASS' if s['ok'] else 'FAIL'
        details = {k:v for k,v in s.items() if k not in ['name','ok']}
        print('  [' + status + '] ' + s['name'] + ': ' + json.dumps(details, ensure_ascii=False))


if __name__ == '__main__':
    main()
