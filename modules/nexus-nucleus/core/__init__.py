# This makes `celery -A core` work and ensures the app is loaded
# when Django starts so @shared_task decorators register correctly.
from .celery import app as celery_app

__all__ = ("celery_app",)
