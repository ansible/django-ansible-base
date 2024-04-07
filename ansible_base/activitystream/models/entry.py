from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _

from ansible_base.lib.abstract_models import AbstractCommonModel, ImmutableCommonModel, ImmutableModel


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

    # This is used for m2m (dis)associations
    related_content_type = models.ForeignKey(ContentType, on_delete=models.DO_NOTHING, null=True, blank=True, related_name='related_content_type')
    related_object_id = models.TextField(null=True, blank=True)
    related_content_object = GenericForeignKey('related_content_type', 'related_object_id')
    related_field_name = models.CharField(max_length=64, null=True, blank=True)

    def __str__(self):
        return f'[{self.created}] {self.get_operation_display()} by {self.created_by}: {self.content_type} {self.object_id}'


class FieldChange(ImmutableModel, AbstractCommonModel):
    """
    Represents a singular change to a field in some model instance.
    """

    allow_anonymous_user_save = True

    class Meta:
        verbose_name_plural = _('Field changes')

    OPERATION_CHOICES = [
        ('added', _('Field added')),
        ('changed', _('Field changed')),
        ('removed', _('Field removed')),
    ]

    entry = models.ForeignKey(Entry, on_delete=models.CASCADE, related_name='changes')
    field_name = models.CharField(max_length=255)
    old_value = models.TextField(null=True, blank=True)
    new_value = models.TextField(null=True, blank=True)
    operation = models.CharField(max_length=7, choices=OPERATION_CHOICES)

    def __str__(self):
        return f'{self.entry.content_type}.{self.field_name}: {self.old_value} -> {self.new_value}'

    @property
    def new_value_as_python(self):
        """
        Return the new value as a Python object, relative to the field type.
        """
        if not self.new_value:
            return self.new_value

        model = self.entry.content_type.model_class()
        field = model._meta.get_field(self.field_name)
        return field.to_python(self.new_value)

    @property
    def old_value_as_python(self):
        """
        Return the old value as a Python object, relative to the field type.
        """
        if not self.old_value:
            return self.old_value

        model = self.entry.content_type.model_class()
        field = model._meta.get_field(self.field_name)
        return field.to_python(self.old_value)


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
