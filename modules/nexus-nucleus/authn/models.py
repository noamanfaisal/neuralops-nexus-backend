import uuid

from django.db import models


class DeviceSession(models.Model):
    """
    Stores this machine's device registration and session state.
    There is typically only one row per Django instance (one device).
    """

    device_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    device_name = models.CharField(max_length=255, default="NeuralOps Desktop")

    STATUS_PENDING = "pending"
    STATUS_ACTIVE = "active"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_EXPIRED, "Expired"),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)

    # Populated once Supabase confirms activation
    user_id = models.CharField(max_length=255, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    session_expires_at = models.DateTimeField(blank=True, null=True)

    # Celery task ID of the running poll task (used to avoid duplicate tasks)
    celery_task_id = models.CharField(max_length=255, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "device_sessions"

    def __str__(self) -> str:
        return f"DeviceSession({self.device_id}, {self.status})"
