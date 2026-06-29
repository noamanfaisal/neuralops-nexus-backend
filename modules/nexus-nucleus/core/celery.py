"""
Celery application for NeuralOps Nucleus.

Workers are started via:
    celery -A core worker -l info -Q neuralops -c 4

Queues:
    neuralops  — default queue for all NeuralOps background tasks
                 (device activation polling, AI calls, etc.)
"""
import os

from celery import Celery

# Tell Django which settings module to use
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

app = Celery("neuralops")

# Pull all Celery config from Django settings (keys prefixed with CELERY_)
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks in all INSTALLED_APPS
app.autodiscover_tasks()
