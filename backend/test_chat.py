import httpx
import asyncio

async def test():
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post('http://localhost:8000/api/v1/auth/register', json={
            'username': 'chattester01',
            'email': 'chattester01@example.com',
            'password': 'Test@123456'
        })
        print('Register:', resp.status_code, resp.json())
        
        resp2 = await client.post('http://localhost:8000/api/v1/auth/login', json={
            'username': 'chattester01',
            'password': 'Test@123456'
        })
        data = resp2.json()
        token = data.get('data', {}).get('access_token', '')
        print('Login:', resp2.status_code, 'token:', bool(token))
        if not token:
            return
        
        resp3 = await client.post('http://localhost:8000/api/v1/chat/sessions', 
            headers={'Authorization': f'Bearer {token}'},
            json={'title': 'test chat'}
        )
        sid = resp3.json()['data']['id']
        print('Session:', sid)
        
        print('--- Streaming ---')
        async with client.stream('POST', 
            f'http://localhost:8000/api/v1/chat/sessions/{sid}/messages',
            headers={'Authorization': f'Bearer {token}'},
            json={'content': '你好'}
        ) as r:
            print('Status:', r.status_code)
            n = 0
            async for line in r.aiter_lines():
                if line.strip():
                    n += 1
                    if n <= 20:
                        print(f'  {line[:200]}')
                    elif n == 21:
                        print('  ...')
            print(f'Total SSE lines: {n}')

asyncio.run(test())
