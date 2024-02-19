from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models.signals import post_save, pre_save, pre_delete
from django.utils.translation import gettext_lazy as _

from ansible_base.lib.abstract_models import CommonModel
from ansible_base.activitystream.signals import (
    activitystream_create,
    activitystream_update,
    # activitystream_delete,
)


class Entry(CommonModel):
    """
    An activity stream entry.

    This is keyed on a generic object_id and content_type, which allows for
    a wide variety of objects to be used in the activity stream.
    """
    class Meta:
        verbose_name_plural = _('Entries')

    OPERATION_CHOICES = [
        ('create', _('Entity created')),
        ('update', _("Entity updated")),
        ('delete', _("Entity deleted")),
        ('associate', _("Entity was associated with another entity")),
        ('disassociate', _("Entity was disassociated with another entity")),
    ]

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.TextField(null=False)
    content_object = GenericForeignKey('content_type', 'object_id')
    operation = models.CharField(max_length=12, choices=OPERATION_CHOICES)
    changes = models.JSONField(null=True, blank=True)

    # TODO: AWX stores denormalized actor data to account for deleted users, we should do the same

    def __str__(self):
        return f'[{self.created_on}] {self.get_operation_display()} by {self.created_by}: {self.content_type} {self.object_id}'


class AuditableModel(models.Model):
    """
    A mixin class that provides integration to the activity stream from any
    model. A model should simply inherit from this class to have its
    create/update/delete events sent to the activity stream.
    """

    class Meta:
        abstract = True

    activity_stream_excluded_field_names = []

    @classmethod
    def connect_signals(cls):
        post_save.connect(activitystream_create, sender=cls, dispatch_uid=f'dab_activitystream_{cls.__name__}_create')
        pre_save.connect(activitystream_update, sender=cls, dispatch_uid=f'dab_activitystream_{cls.__name__}_update')
        # pre_delete.connect(activitystream_delete, sender=cls, dispatch_uid=f'dab_activitystream_{cls.__name__}_delete')
