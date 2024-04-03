import logging
from collections import OrderedDict

from django.conf import settings
from django.db import models
from django.db.models.fields.reverse_related import ManyToManyRel
from django.urls.exceptions import NoReverseMatch
from inflection import underscore
from rest_framework.reverse import reverse

from ansible_base.lib.abstract_models.immutable import ImmutableModel
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING, ansible_encryption
from ansible_base.lib.utils.models import current_user_or_system_user

logger = logging.getLogger('ansible_base.lib.abstract_models.common')


def get_cls_view_basename(cls):
    # This gives the expected base Django view name of cls
    if hasattr(cls, 'router_basename'):
        return cls.router_basename
    return underscore(cls.__name__)


def get_url_for_object(obj, request=None):
    # get_absolute_url mainly exists to support AWX
    if hasattr(obj, 'get_absolute_url'):
        return obj.get_absolute_url()

    basename = get_cls_view_basename(obj.__class__)

    try:
        return reverse(f'{basename}-detail', kwargs={'pk': obj.pk})
    except NoReverseMatch:
        logger.debug(f"Tried to reverse {basename}-detail for model {obj.__class__.__name__} but said view is not defined")
        return ''


class ModifiableModel(models.Model):
    class Meta:
        abstract = True

    modified = models.DateTimeField(
        editable=False,
        help_text="The date/time this resource was created",
        auto_now=True,
    )
    modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='%(app_label)s_%(class)s_modified+',
        default=None,
        null=True,
        editable=False,
        on_delete=models.DO_NOTHING,
        help_text="The user who last modified this resource",
    )

    def save(self, *args, **kwargs):
        '''
        This save function will provide the following features automatically.
          * It will automatically add the modified fields for changing items
        '''
        update_fields = list(kwargs.get('update_fields', []))

        if 'modified_by' not in update_fields:
            self.modified_by = current_user_or_system_user()
            update_fields.append('modified_by')

        return super().save(*args, **kwargs)


class CreatableModel(models.Model):
    class Meta:
        abstract = True

    created = models.DateTimeField(
        editable=False,
        help_text="The date/time this resource was created",
        auto_now_add=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='%(app_label)s_%(class)s_created+',
        default=None,
        null=True,
        editable=False,
        on_delete=models.DO_NOTHING,
        help_text="The user who created this resource",
    )

    def save(self, *args, **kwargs):
        '''
        This save function will provide the following features automatically.
          * It will automatically add a created_by fields for new items
        '''
        update_fields = list(kwargs.get('update_fields', []))

        if not self.pk:
            if self.created_by is None:
                self.created_by = current_user_or_system_user()
                update_fields.append('created_by')

        return super().save(*args, **kwargs)


class AbstractCommonModel(models.Model):
    # Any field marked as encrypted will automatically be stored in an encrypted fashion
    encrypted_fields = []
    # Any field set in here will not be used in the views
    ignore_relations = []

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        '''
        This save function will provide the following features automatically.
          * It will automatically encrypt any fields in the classes `encrypt_fields` property
        '''
        # Encrypt any fields
        for field in self.encrypted_fields:
            field_value = getattr(self, field, None)
            if field_value:
                setattr(self, field, ansible_encryption.encrypt_string(field_value))

        return super().save(*args, **kwargs)

    @classmethod
    def from_db(self, db, field_names, values):
        instance = super().from_db(db, field_names, values)

        for field in self.encrypted_fields:
            field_value = getattr(instance, field, None)
            if field_value and field_value.startswith(ENCRYPTED_STRING):
                setattr(instance, field, ansible_encryption.decrypt_string(field_value))

        return instance

    def get_summary_fields(self, view=None):
        response = {}
        for field in self._meta.fields:
            if isinstance(field, models.ForeignObject) and getattr(self, field.name):
                # ignore relations on inherited django models
                if field.name.endswith("_ptr"):
                    continue
                if hasattr(getattr(self, field.name), 'summary_fields'):
                    response[field.name] = getattr(self, field.name).summary_fields()
        return response

    def related_fields(self, request):
        response = {}
        # See docs/lib/default_models.md
        # Automatically add all of the ForeignKeys for the model as related fields
        for field in self._meta.concrete_fields:
            if field.name in self.ignore_relations:
                continue
            # ignore relations on inherited django models
            if not isinstance(field, models.ForeignKey) or field.name.endswith("_ptr"):
                continue

            if obj := getattr(self, field.name):
                if related_url := get_url_for_object(obj):
                    response[field.name] = related_url

        basename = get_cls_view_basename(self.__class__)

        # Add any reverse relations required
        for relation in self._meta.related_objects + self._meta.many_to_many:
            field_name = relation.name
            # obey the model ignore list
            # skip reverse m2m, we only want to manage associations via the forward
            if field_name in self.ignore_relations or isinstance(relation, ManyToManyRel):
                continue
            reverse_view = f"{basename}-{field_name}-list"
            try:
                response[field_name] = reverse(reverse_view, kwargs={'pk': self.pk})
            except NoReverseMatch:
                logger.error(f"Wanted to add {reverse_view} for {self.__class__} but view was missing")

        sorted_response = OrderedDict()
        sorted_keys = list(response.keys())
        sorted_keys.sort()
        for key in sorted_keys:
            sorted_response[key] = response[key]
        return sorted_response

    def summary_fields(self):
        response = {}
        response['id'] = self.id
        return response


class CommonModel(AbstractCommonModel, CreatableModel, ModifiableModel):
    """
    A base model for most django-ansible-base apps to extend from.
    Includes fields for tracking creation and last-modification metadata.
    """

    class Meta:
        abstract = True


class NamedCommonModel(CommonModel):
    class Meta:
        abstract = True

    name = models.CharField(
        max_length=512,
        help_text="The name of this resource",
    )

    def summary_fields(self):
        res = super().summary_fields()
        res['name'] = self.name
        return res

    def __str__(self):
        return self.name


class UniqueNamedCommonModel(CommonModel):
    class Meta:
        abstract = True

    name = models.CharField(
        max_length=512,
        unique=True,
        help_text="The name of this resource",
    )

    def summary_fields(self):
        res = super().summary_fields()
        res['name'] = self.name
        return res

    def __str__(self):
        return self.name


class ImmutableCommonModel(ImmutableModel, AbstractCommonModel, CreatableModel):
    """
    A save-once (immutable) base model.
    Functionally similar to CommonModel, but does not allow modification of the object after creation
    and does not include the modified/modifed_by fields.
    """

    class Meta:
        abstract = True
