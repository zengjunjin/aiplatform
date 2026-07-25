"""Celery worker entry point.

Used by `celery -A celery_worker worker ...` to locate the Celery app.
"""

from app.tasks.celery_app import celery_app

__all__ = ["celery_app"]
