import functools

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.http import urlencode
from django.utils.translation import gettext_lazy as _

from ansible_base.lib.abstract_models import ImmutableCommonModel
from ansible_base.lib.utils.response import get_relative_url


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

    content_type = models.ForeignKey(ContentType, on_delete=models.DO_NOTHING, help_text=_("The content type which was changed in this entry."))
    object_id = models.TextField(null=True, blank=True, help_text=_("The object id which was modified in this entry."))
    content_object = GenericForeignKey('content_type', 'object_id')
    operation = models.CharField(
        max_length=12, choices=OPERATION_CHOICES, help_text=_("The type of change recorded by the entry (i.e. create/update/delete/etc).")
    )
    changes = models.JSONField(null=True, blank=True, help_text=_("The changes to the system recorded by this entry."))

    # This is used for m2m (dis)associations
    related_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.DO_NOTHING,
        null=True,
        blank=True,
        related_name='related_content_type',
        help_text=_("The content type if this entry is recording an many to many (M2M) change."),
    )
    related_object_id = models.TextField(
        null=True,
        blank=True,
        help_text=_("The object id of the related model if this entry is for an many to many (M2M) change."),
    )
    related_content_object = GenericForeignKey('related_content_type', 'related_object_id')
    related_field_name = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text=_("The related field name if this entry is for an many to many (M2M) relationship."),
    )

    def __str__(self):
        return f'[{self.created}] {self.get_operation_display()} by {self.created_by}: {self.content_type} {self.object_id}'

    @functools.cached_property
    def changed_fk_fields(self):
        """
        :return: A dictionary of {field_name: pk} for any ForeignKey fields that have changed.
            the pk is the new pk value, for changed fields. In the case of added/removed fields,
            the pk is the pk of the related object. In the case of a changed field, the pk is the
            new pk value.
        """
        changed_fks = {}

        if self.changes is None:
            return changed_fks

        for op in ('added_fields', 'changed_fields', 'removed_fields'):
            for field_name, value in self.changes.get(op, {}).items():
                if (model := self.content_type.model_class()) is None:
                    continue
                field = model._meta.get_field(field_name)
                if isinstance(field, models.ForeignKey):
                    try:
                        fk_model = field.related_model
                    except AttributeError:  # Likely the model was deleted
                        continue
                    # For added/removed fields, the value is the pk of the related object
                    # For changed fields, the value is the *new* pk value
                    pk = value[1] if op == 'changed_fields' else value
                    changed_fks[field_name] = (fk_model, pk)

        return changed_fks


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

    def extra_related_fields(self, request):
        content_type = ContentType.objects.get_for_model(self)
        query_kwargs = {
            'content_type': content_type.pk,
            'object_id': self.pk,
        }
        activity_stream_url = get_relative_url('activitystream-list') + '?' + urlencode(query_kwargs)
        return {
            'activity_stream': activity_stream_url,
        }
