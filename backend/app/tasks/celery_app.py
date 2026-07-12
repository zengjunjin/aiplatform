from celery import Celery
from celery.schedules import crontab
from app.config import settings

celery_app = Celery(
    "rag_platform",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

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
}

celery_app.autodiscover_tasks(["app.tasks"])