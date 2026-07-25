import asyncio

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init, worker_process_shutdown
from kombu import Queue
from loguru import logger

from app.config import settings

celery_app = Celery(
    "rag_platform",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)


def _route_task(name, args, kwargs, options, task=None, **kw):
    """按 task name 前缀路由到不同队列（实现 spec 中通配符语义）。

    - app.tasks.document_task.* → queue_parsing
    - app.tasks.evaluation_task.* → queue_evaluation
    - app.tasks.feedback_analysis_task.* → queue_default
    - 其余任务 → queue_default（Celery 默认行为）
    """
    if name.startswith("app.tasks.document_task."):
        return {"queue": "queue_parsing"}
    if name.startswith("app.tasks.evaluation_task."):
        return {"queue": "queue_evaluation"}
    if name.startswith("app.tasks.feedback_analysis_task."):
        return {"queue": "queue_default"}
    return None


celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,
    task_soft_time_limit=240,
    worker_prefetch_multiplier=1,
    task_acks_late=True,  # 任务完成后才 ACK，防止 worker 崩溃任务丢失
    worker_max_tasks_per_child=100,  # 每个 worker 子进程最多执行 100 个任务后重启，防止内存泄漏
    broker_connection_retry_on_startup=True,  # 启动时 broker 不可用自动重试（Celery 5.3+ 必需）
    result_expires=3600,  # 结果 1 小时后过期
    # Task 31: 按任务类型分队列，避免长任务阻塞短任务
    task_routes=(_route_task,),
    task_queues=(
        Queue("queue_parsing"),
        Queue("queue_evaluation"),
        Queue("queue_default"),
        Queue("dead_letter"),
    ),
    # worker 崩溃时拒绝任务（requeue 供其他 worker 处理）
    task_reject_on_worker_lost=True,
    task_default_queue="queue_default",
)

# 定时任务调度
celery_app.conf.beat_schedule = {
    "feedback-analysis-weekly": {
        "task": "app.tasks.feedback_analysis_task.run_feedback_analysis",
        "schedule": crontab(hour=3, minute=0, day_of_week=0),  # 每周日凌晨 3:00
        "options": {
            "expires": 3600,  # 任务过期时间 1 小时
        },
    },
    "scheduled-evaluation-daily": {
        "task": "scheduled_evaluation_task",
        "schedule": crontab(hour=2, minute=0),  # 每日 02:00 (Asia/Shanghai)
        "options": {
            "expires": 3600,  # 任务过期时间 1 小时
        },
    },
}

celery_app.autodiscover_tasks(["app.tasks"])


# ---------- Worker 进程级 EventBus 生命周期管理 ----------
# Bug 11: 原先 document_task._publish 每次都 EventBus.init() + EventBus.close(),
# 导致 Redis 连接与 listener task 泄漏。改为在 worker 进程启动时初始化一次,
# 进程关闭时清理一次,任务中仅调用 publish。
@worker_process_init.connect
def init_eventbus(**kwargs):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        loop.run_until_complete(_do_eventbus_init())
    except Exception as e:
        logger.warning(f"EventBus init failed: {e}")


@worker_process_shutdown.connect
def close_eventbus(**kwargs):
    try:
        loop = asyncio.get_event_loop()
        if not loop.is_closed():
            loop.run_until_complete(_do_eventbus_close())
    except Exception as e:
        logger.debug(f"EventBus close on worker shutdown failed: {e}")


async def _do_eventbus_init():
    from app.core.events import EventBus

    await EventBus.init()


async def _do_eventbus_close():
    from app.core.events import EventBus

    await EventBus.close()
