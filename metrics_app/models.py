from django.db import models

# Create your models here.
from ansible_base.lib.abstract_models import CommonModel


class Metrics(CommonModel):
    service = models.CharField(max_length=32)
    payload = models.JSONField(default=dict)
