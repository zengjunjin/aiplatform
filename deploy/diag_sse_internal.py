"""容器内 SSE 并发自检：绕过 Windows Docker 端口转发层，直打 localhost:8000。

验证 T10 连接池修复后，后端自身在并发 SSE 下是否稳定（[DONE] 完成率）。
"""
import asyncio
import json
import sys

import httpx

BASE = "http://localhost:8000/api/v1"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 20


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=120.0) as c:
        # 注册并登录临时用户
        uname = f"ssecheck_{N}_{asyncio.get_event_loop().time():.0f}"
        await c.post("/auth/register", json={
            "username": uname, "email": f"{uname}@test.com", "password": "Test@123456",
        })
        r = await c.post("/auth/login", json={"username": uname, "password": "Test@123456"})
        token = r.json()["data"]["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        # 创建 session（带 kb=None 直接闲聊，不依赖 KB 数据）
        r = await c.post("/chat/sessions", json={"title": "sse-check"}, headers=h)
        sid = r.json()["data"]["id"]

        async def one(i: int) -> str:
            try:
                done = False
                chunks = 0
                async with c.stream(
                    "POST", f"/chat/sessions/{sid}/messages", headers=h,
                    json={"content": f"用一句话回答：{i}+1 等于几？"},
                ) as resp:
                    if resp.status_code != 200:
                        return f"http_{resp.status_code}"
                    async for line in resp.aiter_lines():
                        if line.startswith("data: [DONE]"):
                            done = True
                            break
                        if line.startswith("data:"):
                            chunks += 1
                return "ok" if done else f"no_done(chunks={chunks})"
            except Exception as e:
                return f"exc:{type(e).__name__}"

        results = await asyncio.gather(*[one(i) for i in range(N)])
        from collections import Counter
        cnt = Counter(results)
        print(json.dumps({"concurrent": N, "results": dict(cnt)}, ensure_ascii=False))


asyncio.run(main())
