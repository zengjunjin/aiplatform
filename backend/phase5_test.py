"""Phase 5 RAG engine acceptance test.

Tests:
1. Hybrid retrieval (BM25 + vector + RRF) on the test KB
2. Reranker (bge-reranker-base) on top candidates
3. RAG prompt construction
4. LLM generation with retrieved context
5. Reference attribution parsing
"""
import asyncio
import json
import os
import sys
import time
import requests

sys.path.insert(0, '.')

BASE = 'http://localhost:8000'
result = {'phase': 5, 'steps': []}


def add(name, ok, **kwargs):
    d = {'name': name, 'ok': ok}
    d.update(kwargs)
    result['steps'].append(d)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def main_async():
    # 1. login (sync HTTP)
    r = requests.post(BASE + '/api/v1/auth/login',
                      json={'username':'admin','password':'admin123'})
    token = r.json().get('data', {}).get('access_token', '')
    add('login', bool(token), status=r.status_code)

    r = requests.get(BASE + '/api/v1/knowledge-bases',
                     headers={'Authorization': 'Bearer ' + token})
    kbs = r.json().get('data', [])
    kb_id = kbs[0]['id'] if kbs else None
    add('kb', kb_id is not None, kb_id=kb_id)

    if not kb_id:
        return

    # 2. Hybrid retrieval
    try:
        from app.rag.retriever import retriever
        t0 = time.time()
        chunks = await retriever.retrieve('What is FastAPI', kb_id, top_k=5)
        elapsed = time.time() - t0
        add('retrieval_hybrid',
            len(chunks) > 0,
            count=len(chunks),
            time_ms=int(elapsed * 1000),
            top_chunk_source=chunks[0].get('source') if chunks else None,
            top_score=chunks[0].get('rrf_score') if chunks else None)
    except Exception as e:
        add('retrieval_hybrid', False, error=str(e))
        return

    # 3. Rerank (may download bge-reranker-base on first run)
    try:
        from app.rag.reranker import reranker
        t0 = time.time()
        reranked = await reranker.rerank('What is FastAPI', chunks, top_k=3)
        elapsed = time.time() - t0
        add('rerank',
            len(reranked) > 0,
            count=len(reranked),
            time_ms=int(elapsed * 1000),
            top_score=reranked[0].get('rerank_score') if reranked else None)
    except Exception as e:
        add('rerank', False, error=str(e)[:200])

    # 4. Prompt construction
    try:
        from app.rag.prompt_builder import build_rag_prompt, build_context_messages, SYSTEM_PROMPT
        top_docs = reranked if reranked else chunks
        rag_context = build_rag_prompt('What is FastAPI?', top_docs[:3])
        messages = build_context_messages(
            SYSTEM_PROMPT, rag_context, [], 'What is FastAPI?'
        )
        add('prompt_build',
            bool(rag_context) and len(messages) > 0,
            prompt_len=len(rag_context),
            messages_count=len(messages))
    except Exception as e:
        add('prompt_build', False, error=str(e)[:200])

    # 5. LLM generation
    try:
        from app.models.factory import ModelFactory
        llm = ModelFactory.create_llm()
        t0 = time.time()
        answer = await llm.chat(messages, temperature=0.3)
        elapsed = time.time() - t0
        add('llm_generate',
            bool(answer) and len(answer) > 10,
            time_ms=int(elapsed * 1000),
            answer_len=len(answer),
            answer_preview=answer[:100])
    except Exception as e:
        add('llm_generate', False, error=str(e)[:200])

    # 6. Reference parsing
    try:
        from app.rag.reference_parser import parse_references
        refs = parse_references(answer, top_docs[:3]) if answer else []
        add('reference_parse',
            True,  # not strictly required to have refs
            refs_count=len(refs))
    except Exception as e:
        add('reference_parse', False, error=str(e)[:200])


def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main_async())
    finally:
        loop.close()

    # Save
    with open(r'G:\aiplatform\backend\phase5_result.json', 'w', encoding='utf-8') as f:
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
