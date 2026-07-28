# ---- Builder stage ----
# 编译期依赖：build-essential / libpq-dev / poetry 仅在此阶段存在，
# 不会进入最终 runtime 镜像，显著减小镜像体积。
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# 锁定 poetry 版本，保证可重现构建
RUN pip install --no-cache-dir poetry==1.8.3

WORKDIR /app

# 仅复制依赖描述文件，最大化利用 Docker 层缓存
COPY pyproject.toml poetry.lock* ./

# 安装依赖到项目内 .venv（virtualenvs.in-project=true）
# --no-root: 不安装当前项目包本身（runtime 阶段会以源码方式运行）
# 注意：pyarrow 15+ 移除了 PyExtensionType，导致 datasets/ragas 无法导入
# 因此 poetry install 后必须降级 pyarrow 到 14.x 保证兼容性
# 同时 pyarrow 14.x 不支持 numpy 2.x，需降级 numpy 到 1.26.x
# scipy 1.14+ 要求 numpy 2.0+ 并引用 np.long（在 1.26 中已移除），
# 需降级 scipy 到 1.13.x（最后兼容 numpy 1.26 的分支），否则
# sentence_transformers -> sklearn -> scipy 加载失败，reranker 无法工作
RUN poetry config virtualenvs.in-project true \
    && poetry install --without dev --no-interaction --no-ansi --no-root \
    && .venv/bin/pip install --no-cache-dir 'pyarrow>=14,<15' 'numpy<2' 'scipy>=1.13,<1.14'

# 替换 torch 为 CPU-only 版本，移除 nvidia CUDA 依赖（约减 5GB 镜像体积）
# 后端容器中 torch 仅用于 reranker (sentence-transformers) 的 CPU 推理，不需要 CUDA
RUN .venv/bin/pip uninstall -y torch nvidia-cublas nvidia-cuda-cupti nvidia-cuda-nvrtc \
    nvidia-cuda-runtime nvidia-cudnn-cu13 nvidia-cufft nvidia-cufile nvidia-curand \
    nvidia-cusolver nvidia-cusparse nvidia-cusparselt-cu13 nvidia-nccl-cu13 \
    nvidia-nvjitlink nvidia-nvshmem-cu13 nvidia-nvtx \
    cuda-bindings cuda-pathfinder cuda-toolkit triton 2>/dev/null; \
    .venv/bin/pip install --no-cache-dir torch==2.12.1 --index-url https://download.pytorch.org/whl/cpu

# 复制源码（.dockerignore 会排除 tests/ storage/ .git/ 等）
COPY . .

# 清理 .pyc 缓存和 __pycache__ 目录，减小镜像体积
RUN find /app -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; \
    find /app -name '*.pyc' -delete 2>/dev/null; \
    true

# ---- Runtime stage ----
# 仅包含运行时所需的系统库与 Python 运行时，不含编译工具链。
FROM python:3.12-slim AS runtime

# 运行时系统依赖：
#   libpq5         - asyncpg / psycopg2 运行时所需
#   poppler-utils  - PDF 解析（pdftotext 等）
#   curl           - docker-compose healthcheck 使用
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        poppler-utils \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 appuser

WORKDIR /app

# 从 builder 复制 .venv 与源码，chown 确保非 root 用户可读
COPY --from=builder --chown=appuser:appuser /app /app

# 清理 .venv 中的缓存文件和不需要的 dist-info，减小镜像体积
RUN find /app/.venv -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; \
    find /app/.venv -name '*.pyc' -delete 2>/dev/null; \
    find /app/.venv -name '*.pyo' -delete 2>/dev/null; \
    rm -rf /app/.venv/share /app/.venv/man 2>/dev/null; \
    true

# 将 .venv 加入 PATH，使 uvicorn / alembic / celery 等命令直接可用
# （docker-compose.yml 中的 `sh -c "alembic upgrade head && uvicorn ..."` 依赖此 PATH）
ENV PATH="/app/.venv/bin:$PATH"

USER appuser

EXPOSE 8000

# Task 90: 容器健康检查 — 探测 /readyz 端点（含 DB/Redis/Qdrant 依赖检查）
# curl 已在 runtime 阶段安装；docker-compose 的 healthcheck 会覆盖此指令，
# 此处保留以便独立运行容器时（docker run）也有健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 CMD curl -f http://localhost:8000/readyz || exit 1

# 预期镜像体积 ≤ 1.5GB（受 torch/scipy/numpy 依赖影响，已通过多阶段构建+缓存清理优化）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
