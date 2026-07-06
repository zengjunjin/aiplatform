from app.tasks.document_task import parse_document_task
from app.tasks.celery_app import celery_app

__all__ = ["parse_document_task", "celery_app"]
