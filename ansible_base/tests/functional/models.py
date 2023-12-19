from django.db import models

from ansible_base.models import AbstractOrganization


class Organization(AbstractOrganization):
    pass


class Team(models.Model):
    name = models.CharField(max_length=512)
