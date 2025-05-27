from ansible_base.lib.abstract_models import CommonModel
from django.db import models

# Create your models here.
class Metric(CommonModel):
    service = models.CharField(max_length=32)
    payload = models.JSONField(default=dict)
