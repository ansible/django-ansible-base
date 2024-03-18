from functools import partial

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models.signals import m2m_changed, post_save, pre_delete, pre_save
from django.utils.translation import gettext_lazy as _

from ansible_base.activitystream.signals import activitystream_create, activitystream_delete, activitystream_m2m_changed, activitystream_update
from ansible_base.lib.abstract_models import ImmutableCommonModel


class Entry(ImmutableCommonModel):
    """
    An activity stream entry.

    This is keyed on a generic object_id and content_type, which allows for
    a wide variety of objects to be used in the activity stream.
    """

    allow_anonymous_user_save = True

    class Meta:
        verbose_name_plural = _('Entries')

    OPERATION_CHOICES = [
        ('create', _('Entity created')),
        ('update', _("Entity updated")),
        ('delete', _("Entity deleted")),
        ('associate', _("Entity was associated with another entity")),
        ('disassociate', _("Entity was disassociated with another entity")),
    ]

    content_type = models.ForeignKey(ContentType, on_delete=models.DO_NOTHING)
    object_id = models.TextField(null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')
    operation = models.CharField(max_length=12, choices=OPERATION_CHOICES)
    changes = models.JSONField(null=True, blank=True)

    # This is used for m2m (dis)associations
    related_content_type = models.ForeignKey(ContentType, on_delete=models.DO_NOTHING, null=True, blank=True, related_name='related_content_type')
    related_object_id = models.TextField(null=True, blank=True)
    related_content_object = GenericForeignKey('related_content_type', 'related_object_id')
    related_field_name = models.CharField(max_length=64, null=True, blank=True)

    def __str__(self):
        return f'[{self.created}] {self.get_operation_display()} by {self.created_by}: {self.content_type} {self.object_id}'


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
        pre_delete.connect(activitystream_delete, sender=cls, dispatch_uid=f'dab_activitystream_{cls.__name__}_delete')

        # Connect to m2m_changed signal for all m2m fields
        for field in cls._meta.many_to_many:
            if field.name in cls.activity_stream_excluded_field_names:
                continue

            fn = partial(activitystream_m2m_changed, field_name=field.name)
            m2m_changed.connect(fn, sender=getattr(cls, field.name).through, dispatch_uid=f'dab_activitystream_{cls.__name__}_{field.name}_m2m_changed')

    @property
    def activity_stream_entries(self):
        """
        A helper property that returns the activity stream entries for this object.
        """
        return Entry.objects.filter(content_type=ContentType.objects.get_for_model(self), object_id=self.pk).order_by('created')
