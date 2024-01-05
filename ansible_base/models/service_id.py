import uuid
from functools import lru_cache

from django.db import models


class ServiceID(models.Model):
    """
    Provides a globally unique ID for this service.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, null=False, editable=False)

    def save(self, *args, **kwargs):
        if self.objects.exists():
            raise RuntimeError("This service already has a ServiceID")

        return super().save()


@lru_cache(maxsize=1)
def service_id():
    system_id_obj = ServiceID.objects.first()
    return str(system_id_obj.pk)
