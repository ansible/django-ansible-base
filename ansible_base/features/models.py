from django.db import models
from django.utils.translation import gettext_lazy as _

from ansible_base.features import get_feature_cache

feature_cache = get_feature_cache()


class FeatureStatus(models.TextChoices):
    ALPHA = "a", _("Alpha")
    BETA = "b", _("Beta")


class Feature(models.Model):
    name = models.TextField(
        null=False,
        editable=False,
        help_text=_("Name of the feature"),
        unique=True,
    )

    description = models.TextField(
        null=False,
        editable=False,
        help_text=_("A description of the feature"),
    )

    short_name = models.TextField(
        max_length=128,
        null=False,
        unique=True,
        editable=False,
        help_text=_("A unique short name used to reference the feature"),
    )

    status = models.CharField(
        null=False,
        max_length=1,
        choices=FeatureStatus.choices,
        default=FeatureStatus.ALPHA,
        help_text=_("The development status of the feature"),
        editable=False,
    )

    requires_restart = models.BooleanField(
        null=False, default=False, editable=False, help_text=_("Does changing the statue of this feature require a restart?")
    )

    enabled = models.BooleanField(
        null=False,
        default=False,
        help_text=_("Is this feature enabled"),
    )

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if feature_cache:
            feature_cache.set(self.short_name, self.enabled)


#    def from_db(cls, db, field_names, values):
#        instance = super().from_db(db, field_names, values)
#        if feature_cache:
#            feature_cache.set(instance.short_name, instance.enabled)
#        return instance
