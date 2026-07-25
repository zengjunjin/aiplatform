"""检查基础设施服务是否就绪"""

import sys

import requests
from sqlalchemy import create_engine, text

from app.config import settings

ok = True

# PostgreSQL
try:
    engine = create_engine(settings.database_url_sync)
    with engine.connect() as c:
        c.execute(text("SELECT 1"))
    print("[OK] PostgreSQL")
except Exception as e:
    print(f"[FAIL] PostgreSQL: {e}")
    ok = False

# Redis
try:
    import redis as redis_lib

    r = redis_lib.from_url(f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}")
    r.ping()
    print("[OK] Redis")
    r.close()
except Exception as e:
    print(f"[FAIL] Redis: {e}")
    ok = False

# Qdrant
try:
    resp = requests.get(
        f"http://{settings.QDRANT_HOST}:{settings.QDRANT_PORT}/collections", timeout=5
    )
    if resp.status_code == 200:
        print("[OK] Qdrant")
    else:
        print(f"[FAIL] Qdrant: HTTP {resp.status_code}")
        ok = False
except Exception as e:
    print(f"[FAIL] Qdrant: {e}")
    ok = False

# Ollama
try:
    resp = requests.get(f"{settings.OLLAMA_HOST}/api/tags", timeout=5)
    if resp.status_code == 200:
        models = resp.json().get("models", [])
        names = [m.get("name", "") for m in models]
        print(f"[OK] Ollama (models: {len(models)})")
        if not any("qwen" in n.lower() for n in names):
            print("[WARN] No qwen model found, may need to pull")
    else:
        print(f"[FAIL] Ollama: HTTP {resp.status_code}")
        ok = False
except Exception as e:
    print(f"[FAIL] Ollama: {e}")
    ok = False

if not ok:
    print("\nSome services are not ready. Start them with Docker:")
    print("  cd deploy && docker-compose up -d postgres redis qdrant ollama")
    sys.exit(1)

print("\nAll services are ready!")
sys.exit(0)
