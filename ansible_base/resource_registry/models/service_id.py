import uuid

from django.db import models


class ServiceID(models.Model):
    """
    Provides a globally unique ID for this service.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, null=False, editable=False)

    def save(self, *args, **kwargs):
        if ServiceID.objects.exists():
            raise RuntimeError("This service already has a ServiceID")

        return super().save()


_service_id = None


def service_id():
    global _service_id
    if not _service_id:
        _service_id = str(ServiceID.objects.first().pk)
    return _service_id
