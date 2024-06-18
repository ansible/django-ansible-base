import logging
from collections import OrderedDict

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.urls.exceptions import NoReverseMatch
from django.utils.translation import gettext_lazy as _
from inflection import underscore
from rest_framework.reverse import reverse

from ansible_base.lib.abstract_models.immutable import ImmutableModel
from ansible_base.lib.utils.encryption import ansible_encryption
from ansible_base.lib.utils.models import current_user_or_system_user, is_system_user

logger = logging.getLogger('ansible_base.lib.abstract_models.common')


def get_cls_view_basename(cls):
    # This gives the expected base Django view name of cls
    if hasattr(cls, 'router_basename'):
        return cls.router_basename
    return underscore(cls.__name__)


def get_url_for_object(obj, request=None, pk=None):
    # get_absolute_url mainly exists to support AWX
    if hasattr(obj, 'get_absolute_url'):
        return obj.get_absolute_url()

    basename = get_cls_view_basename(obj.__class__)

    try:
        return reverse(f'{basename}-detail', kwargs={'pk': pk or obj.pk})
    except NoReverseMatch:
        logger.debug(f"Tried to reverse {basename}-detail for model {obj.__class__.__name__} but said view is not defined")
        return ''


class ModifiableModel(models.Model):
    class Meta:
        abstract = True

    modified = models.DateTimeField(
        editable=False,
        help_text=_("The date/time this resource was created"),
        auto_now=True,
    )
    modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='%(app_label)s_%(class)s_modified+',
        default=None,
        null=True,
        editable=False,
        on_delete=models.SET_NULL,
        help_text=_("The user who last modified this resource"),
    )

    def save(self, *args, **kwargs):
        '''
        This save function will provide the following features automatically.
          * It will automatically add the modified fields for changing items

        There are several edge cases to be aware of:
          * If the user is logging in and their "last_login" field is getting
            changed (in their user model instance), then we do not update
            "modified_by". (This is so they can see if someone changed their
            user object while they were away).
          * If no fields in update_fields are "editable", then we don't update
            "modified_by".
          * "modified" is updated in every case, since it's an auto_now
            timestamp.
        '''
        has_update_fields = kwargs.get('update_fields') is not None
        update_fields = kwargs.get('update_fields', [])
        if update_fields is None:
            update_fields = []
        else:
            update_fields = list(update_fields)
        is_user_logging_in = isinstance(self, AbstractUser) and update_fields == ['last_login']
        has_editable_field = any(self._meta.get_field(field).editable for field in update_fields)

        if 'modified_by' in update_fields:
            # Explicit update of modified_by, don't mess with it
            pass
        elif is_user_logging_in:
            # User is logging in, only last_login is changing, don't update modified_by
            pass
        elif has_update_fields and not has_editable_field:
            # No editable fields are changing, don't update modified_by
            pass
        elif not self.pk and is_system_user(self):
            # If we are building the system user we can't set the modified_by or it will error (because it would be system which isn't built yet)
            pass
        else:
            self.modified_by = current_user_or_system_user()
            update_fields.append('modified_by')
            if has_update_fields:
                kwargs['update_fields'] = update_fields

        return super().save(*args, **kwargs)


class CreatableModel(models.Model):
    class Meta:
        abstract = True

    created = models.DateTimeField(
        editable=False,
        help_text=_("The date/time this resource was created"),
        auto_now_add=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='%(app_label)s_%(class)s_created+',
        default=None,
        null=True,
        editable=False,
        on_delete=models.SET_NULL,
        help_text=_("The user who created this resource"),
    )

    def save(self, *args, **kwargs):
        '''
        This save function will provide the following features automatically.
          * It will automatically add a created_by fields for new items
        '''

        if not self.pk and not is_system_user(self):
            if self.created_by is None:
                self.created_by = current_user_or_system_user()

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
            if field_value:
                setattr(instance, field, ansible_encryption.decrypt_string(field_value))

        return instance

    def get_summary_fields(self):
        response = {}
        for field in self._meta.fields:
            if isinstance(field, models.ForeignObject) and getattr(self, field.name):
                # ignore relations on inherited django models
                if field.name.endswith("_ptr") or (field.name in self.ignore_relations):
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
        missing_relations = []
        for relation in self._meta.related_objects + self._meta.many_to_many:
            field_name = relation.name
            # obey the model ignore list
            if field_name in self.ignore_relations:
                continue
            reverse_view = f"{basename}-{field_name}-list"
            try:
                response[field_name] = reverse(reverse_view, kwargs={'pk': self.pk})
            except NoReverseMatch:
                missing_relations.append(reverse_view)

        if missing_relations and settings.DEBUG:
            logger.error(f"Wanted to add {', '.join(missing_relations)} for {self.__class__} but view was missing")

        if hasattr(self, 'extra_related_fields'):
            response.update(self.extra_related_fields(request))

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
        help_text=_("The name of this resource"),
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
        help_text=_("The name of this resource"),
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
