"""Phase 4 end-to-end pipeline test.

Handles the case where the test document already exists in the KB
(409 Conflict) by reusing the existing document_id and triggering
a reparse.
"""
import requests, json, time, os, sys

sys.path.insert(0, '.')
BASE = 'http://localhost:8000'
result = {'steps': []}

# 1. login
r = requests.post(BASE + '/api/v1/auth/login',
                  json={'username':'admin','password':'admin123'})
data = r.json()
token = data.get('data', {}).get('access_token', '')
result['steps'].append({'name':'login','ok':bool(token),'status':r.status_code})
headers = {'Authorization': 'Bearer ' + token}

# 2. KB
r = requests.get(BASE + '/api/v1/knowledge-bases', headers=headers)
kbs = r.json().get('data', [])
if isinstance(kbs, list) and len(kbs) > 0:
    kb_id = kbs[0]['id']
    result['steps'].append({'name':'kb','ok':True,'kb_id':kb_id,'action':'existing'})
else:
    r = requests.post(BASE + '/api/v1/knowledge-bases',
                      json={'name':'Test KB','description':'test'},
                      headers=headers)
    kb_id = r.json().get('data', {}).get('id')
    result['steps'].append({'name':'kb','ok':bool(kb_id),'kb_id':kb_id,'action':'created'})

# 3. test file
test_file = r'G:\aiplatform\backend\test_doc.md'
exists = os.path.exists(test_file)
result['steps'].append({'name':'test_file','ok':exists,
                        'size':os.path.getsize(test_file) if exists else 0})

doc_id = None
task_id = None

if exists and kb_id:
    # 4. upload
    with open(test_file, 'rb') as f:
        files = {'file': ('test_doc.md', f, 'text/markdown')}
        form_data = {'kb_id': str(kb_id)}
        r = requests.post(BASE + '/api/v1/documents/upload',
                          files=files, data=form_data, headers=headers)
    upload_data = r.json()
    if r.status_code == 200 and upload_data.get('data'):
        doc_id = upload_data['data'].get('document_id')
        task_id = upload_data['data'].get('task_id')
        result['steps'].append({'name':'upload','ok':bool(doc_id),
                                'status':r.status_code,
                                'doc_id':doc_id,'task_id':task_id})
    else:
        # probably 409 conflict - try to reuse existing doc
        result['steps'].append({'name':'upload','ok':False,
                                'status':r.status_code,
                                'response':upload_data})
        # list documents to find existing one
        r = requests.get(BASE + '/api/v1/documents',
                         params={'kb_id': kb_id},
                         headers=headers)
        docs = r.json().get('data', [])
        if docs:
            doc_id = docs[0].get('id')
            result['steps'].append({'name':'reuse_doc','ok':bool(doc_id),
                                    'doc_id':doc_id})

if doc_id:
    # Trigger reparse (in case it failed earlier or to test reparse)
    r = requests.post(BASE + '/api/v1/documents/' + str(doc_id) + '/reparse',
                      headers=headers)
    if r.status_code == 200:
        task_id = r.json().get('data', {}).get('task_id')
        result['steps'].append({'name':'reparse','ok':True,'task_id':task_id})
    else:
        result['steps'].append({'name':'reparse','ok':False,
                                'status':r.status_code,'body':r.json()})

    # Poll progress
    final_status = None
    final_chunks = 0
    final_error = None
    polls = 0
    for i in range(60):
        time.sleep(3)
        r = requests.get(BASE + '/api/v1/documents/' + str(doc_id) + '/progress',
                         headers=headers)
        d = r.json().get('data', {})
        final_status = d.get('status')
        final_chunks = d.get('chunk_count', 0)
        final_error = d.get('error_message')
        polls = i + 1
        if final_status in ('done', 'failed'):
            break
    result['steps'].append({'name':'pipeline',
                            'ok': final_status == 'done',
                            'status': final_status,
                            'chunks': final_chunks,
                            'error': final_error,
                            'polls': polls})

    # Chroma
    try:
        import chromadb
        client = chromadb.PersistentClient(path='./chroma_data')
        collections = client.list_collections()
        col_names = [c.name for c in collections]
        target_col = 'chunks_kb_' + str(kb_id)
        if target_col in col_names:
            col = client.get_collection(target_col)
            chroma_count = col.count()
        else:
            chroma_count = 0
        result['steps'].append({'name':'chroma',
                                'ok':chroma_count > 0,
                                'collections':col_names,
                                'count':chroma_count})
    except Exception as e:
        result['steps'].append({'name':'chroma','ok':False,'error':str(e)})

    # PG chunks count
    try:
        from app.db.sync_session import get_sync_session
        from app.db.document_chunk import DocumentChunk
        from sqlalchemy import select, func
        session = get_sync_session()
        try:
            cnt = session.execute(
                select(func.count()).where(DocumentChunk.doc_id == doc_id)
            ).scalar()
            result['steps'].append({'name':'pg_chunks',
                                    'ok': cnt is not None and cnt > 0,
                                    'count': cnt})
        finally:
            session.close()
    except Exception as e:
        result['steps'].append({'name':'pg_chunks','ok':False,'error':str(e)})

    # BM25 sync search
    try:
        from app.rag.bm25 import bm25_store
        # Get chunks from PG for search test
        from app.db.sync_session import get_sync_session
        from app.db.document_chunk import DocumentChunk
        from sqlalchemy import select
        session = get_sync_session()
        try:
            db_chunks = session.execute(
                select(DocumentChunk).where(DocumentChunk.doc_id == doc_id)
                .order_by(DocumentChunk.chunk_index)
            ).scalars().all()
            chunk_dicts = [{'content': c.content, 'char_count': c.char_count} for c in db_chunks]
        finally:
            session.close()
        # Sync search test
        results_search = bm25_store.search_sync(kb_id, 'FastAPI', top_k=5, chunks=chunk_dicts)
        result['steps'].append({'name':'bm25_search',
                                'ok': len(results_search) > 0,
                                'hits': len(results_search)})
    except Exception as e:
        result['steps'].append({'name':'bm25_search','ok':False,'error':str(e)})

# Save
with open(r'G:\aiplatform\backend\phase4_result.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

passed = sum(1 for s in result['steps'] if s['ok'])
total = len(result['steps'])
print('Result: ' + str(passed) + '/' + str(total) + ' PASS')
for s in result['steps']:
    status = 'PASS' if s['ok'] else 'FAIL'
    details = {k:v for k,v in s.items() if k not in ['name','ok']}
    print('  [' + status + '] ' + s['name'] + ': ' + json.dumps(details, ensure_ascii=False))
