import logging
from collections import OrderedDict

from crum import get_current_user
from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.models.fields.reverse_related import ManyToManyRel
from django.urls.exceptions import NoReverseMatch
from inflection import underscore
from rest_framework.reverse import reverse

from ansible_base.lib.utils.encryption import ENCRYPTED_STRING, ansible_encryption
from ansible_base.lib.utils.models import get_system_user

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


class CommonModel(models.Model):
    # Any field marked as encrypted will automatically be stored in an encrypted fashion
    encrypted_fields = []
    # Any field set in here will not be used in the views
    ignore_relations = []

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
        This save function will provide several features automatically.
          * It will automatically encrypt any fields in the classes `encrypt_fields` property
          * It will automatically add a created_by fields for new items
          * It will automatically add the modified fields for changing items
        '''
        update_fields = list(kwargs.get('update_fields', []))

        # Manually perform auto_now_add and auto_now logic.
        user = get_current_user()
        if user is None or user.is_anonymous:
            user = get_system_user()

        if not self.pk:
            if self.created_by is None:
                self.created_by = user
                update_fields.append('created_by')

        if 'modified_by' not in update_fields:
            self.modified_by = user
            update_fields.append('modified_by')

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

    def get_summary_fields(self):
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


class ImmutableModel:
    # In case the model is extending CommonModel.
    modified_on = None
    modified_by = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        # MRO dictates that we must be first.
        if cls.__bases__[0] is not ImmutableModel:
            raise ValueError(f"ImmutableModel must be the first base class for {cls.__name__}")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError(f"{self.__class__.__name__} is immutable and cannot be modified.")

        return super().save(*args, **kwargs)

    def __getattribute__(self, name):
        # This is a bit of a hack, there is no good way to remove these fields, because they exist up the chain
        # if the model inherits from CommonModel.
        if name in ('modified_on', 'modified_by'):
            raise FieldDoesNotExist(f"{self.__class__.__name__} has no attribute {name}")

        return super().__getattribute__(name)
