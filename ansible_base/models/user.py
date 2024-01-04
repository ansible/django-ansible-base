from django.utils.translation import gettext_lazy as _
from django.contrib.auth.models import AbstractUser
from django.db import models


class AnsibleBaseUser(AbstractUser):
    class Meta:
        abstract = True

    is_system_auditor = models.BooleanField(
        _("superauditor status"),
        default=False,
        help_text=_(
            "Designates that this user can view everything in the system "
            "without explicitly assigning view permissions."
        )
    )

    def summary_fields(self):
        return {
            'id': self.id,
            'username': self.username,
            'first_name': self.first_name,
            'last_name': self.last_name,
        }
