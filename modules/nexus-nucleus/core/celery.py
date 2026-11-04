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


from celery.signals import worker_ready  # noqa: E402


@worker_ready.connect
def _refresh_models_catalog_on_start(sender=None, **kwargs):
    """The model catalog is checked at start-up as well as daily (owner,
    2026-11-04) -- queued, so a slow or offline download never holds the
    worker up."""
    try:
        sender.app.send_task("intelligence.tasks.refresh_models_catalog", countdown=10)
    except Exception:  # noqa: BLE001 -- never block the worker on this
        pass
