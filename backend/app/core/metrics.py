from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

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


def get_metrics_content():
    return generate_latest()


def get_metrics_content_type():
    return CONTENT_TYPE_LATEST
