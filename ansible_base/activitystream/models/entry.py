import functools

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _

from ansible_base.lib.abstract_models import ImmutableCommonModel


class Entry(ImmutableCommonModel):
    """
    An activity stream entry.

    This is keyed on a generic object_id and content_type, which allows for
    a wide variety of objects to be used in the activity stream.
    """

    router_basename = 'activitystream'

    class Meta:
        verbose_name_plural = _('Entries')
        ordering = ['id']

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

    @functools.cached_property
    def changed_fk_fields(self):
        """
        :return: A dictionary of {field_name: pk} for any ForeignKey fields that have changed.
            the pk is the new pk value, for changed fields.
        """
        changed_fks = {}

        if self.changes is None:
            return changed_fks

        for op in ('added_fields', 'changed_fields', 'removed_fields'):
            for field_name, value in self.changes.get(op, {}).items():
                field = self.content_type.model_class()._meta.get_field(field_name)
                if isinstance(field, models.ForeignKey):
                    if op == 'changed_fields':
                        pk = value[1]
                    else:
                        pk = value
                    changed_fks[field_name] = pk

        return changed_fks

    @functools.cached_property
    def content_object_with_prefetched_changed_fields(self):
        """
        Get the content object with any changed ForeignKey fields prefetched.
        This is useful for related and summary_fields in serializers.

        :return: The content object with any changed ForeignKey fields prefetched.
        """
        if self.changes is None:
            return self.content_object

        changed_fks = self.changed_fk_fields.keys()
        obj = self.content_type.model_class().objects.select_related(*changed_fks).get(pk=self.object_id)
        return obj


class AuditableModel(models.Model):
    """
    A mixin class that provides integration to the activity stream from any
    model. A model should simply inherit from this class to have its
    create/update/delete events sent to the activity stream.
    """

    class Meta:
        abstract = True

    # Adding field names to this list will exclude them from the activity stream changes dictionaries
    activity_stream_excluded_field_names = []

    # Adding field names to this list will limit the activity stream changes dictionaries to only include these fields
    activity_stream_limit_field_names = []

    @property
    def activity_stream_entries(self):
        """
        A helper property that returns the activity stream entries for this object.
        """
        return Entry.objects.filter(content_type=ContentType.objects.get_for_model(self), object_id=self.pk).order_by('created')
