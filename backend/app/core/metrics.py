from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

REQUEST_TOTAL = Counter(
    "rag_http_requests_total",
    "Total number of HTTP requests",
    ["method", "path", "status_code"],
)

REQUEST_LATENCY = Histogram(
    "rag_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

REQUEST_IN_PROGRESS = Gauge(
    "rag_http_requests_in_progress",
    "Number of HTTP requests currently in progress",
)

RAG_RETRIEVAL_TOTAL = Counter(
    "rag_retrievals_total",
    "Total number of RAG retrievals",
    ["kb_id"],
)

ACTIVE_SESSIONS = Gauge(
    "rag_active_sessions",
    "Number of active chat sessions",
)

TOTAL_DOCUMENTS = Gauge(
    "rag_documents_total",
    "Total number of documents in the system",
)

TOTAL_USERS = Gauge(
    "rag_users_total",
    "Total number of registered users",
)

DB_POOL_SIZE = Gauge(
    "rag_db_pool_size",
    "Database connection pool size",
)

DB_POOL_IN_USE = Gauge(
    "rag_db_pool_in_use",
    "Number of database connections currently in use",
)

DB_POOL_IDLE = Gauge(
    "rag_db_pool_idle",
    "Number of idle database connections in the pool",
)

RAG_RETRIEVAL_LATENCY = Histogram(
    "rag_retrieval_latency_seconds",
    "RAG retrieval latency in seconds",
    ["stage"],  # vector, bm25, rrf, rerank, total
)

RAG_LLM_TTFT = Histogram(
    "rag_llm_ttft_seconds",
    "Time to first token in seconds",
    ["model"],
)

RAG_LLM_TOKENS_PER_SECOND = Gauge(
    "rag_llm_tokens_per_second",
    "Token generation rate",
    ["model"],
)

RAG_E2E_LATENCY = Histogram(
    "rag_e2e_latency_seconds",
    "End-to-end latency in seconds",
    ["kb_id"],
)

RAG_DOCUMENT_COUNT = Gauge(
    "rag_document_count",
    "Number of documents in knowledge base",
    ["kb_id"],
)

# Task 14: Embedding 缓存命中率监控
EMBEDDING_CACHE_HITS = Counter(
    "embedding_cache_hits_total",
    "Total number of embedding cache hits",
)

EMBEDDING_CACHE_MISSES = Counter(
    "embedding_cache_misses_total",
    "Total number of embedding cache misses",
)

EMBEDDING_CACHE_ERRORS = Counter(
    "embedding_cache_errors_total",
    "Total number of embedding cache errors (Redis connection/decode failures)",
)

# ---------------------------------------------------------------------------
# Phase 5 / H33: 业务自定义指标
# ---------------------------------------------------------------------------

# KB 创建数（按用户角色细分，用于审计与配额监控）
KB_CREATED_TOTAL = Counter(
    "rag_kb_created_total",
    "Total number of knowledge bases created",
    ["user_role"],
)

# 文档解析成功 / 失败计数（失败按原因细分，用于解析质量监控）
DOC_PARSE_SUCCESS_TOTAL = Counter(
    "rag_doc_parse_success_total",
    "Total documents successfully parsed",
)

DOC_PARSE_FAILURE_TOTAL = Counter(
    "rag_doc_parse_failure_total",
    "Total documents failed to parse",
    ["failure_reason"],
)

# 聊天端到端响应时间直方图（与 RAG_E2E_LATENCY 区别：
# RAG_E2E_LATENCY 按 kb_id 细分用于定位单 KB 性能瓶颈；
# 本指标不细分标签，用于整体 P95/P99 SRE SLO 监控，桶覆盖 0.5s~120s）
CHAT_RESPONSE_DURATION = Histogram(
    "rag_chat_response_duration_seconds",
    "Chat response duration in seconds",
    buckets=[0.5, 1, 2, 5, 10, 30, 60, 120],
)

# 活跃用户会话数（当前已登录但未主动 logout 的会话数）
# 修复（v0.4.0）：修正指标语义
# 原实现：login 时 inc()、logout 时 dec()，但 token 过期不 dec 导致计数只增不减
# 修正说明：本指标衡量的是"当前未注销的会话数"，非"5 分钟内活跃用户"
# 真正的活跃用户统计应基于 Redis session TTL 周期性 set，后续可扩展
ACTIVE_USERS = Gauge(
    "rag_active_users",
    "Number of active logged-in sessions (not yet logged out)",
)

# LLM 推理耗时直方图（按模型细分，P99 用于推理超时告警）
# 与 RAG_LLM_TTFT 区别：TTFT 衡量首 token 延迟，本指标衡量完整推理耗时
LLM_INFERENCE_DURATION = Histogram(
    "rag_llm_inference_duration_seconds",
    "LLM inference duration in seconds",
    ["model"],
    buckets=[0.5, 1, 2, 5, 10, 30, 60, 120],
)


def get_metrics_content():
    return generate_latest()


def get_metrics_content_type():
    return CONTENT_TYPE_LATEST
