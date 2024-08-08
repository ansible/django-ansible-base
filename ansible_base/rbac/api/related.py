import logging
from typing import Optional

from django.conf import settings
from django.db.models import Field, ForeignKey, Model
from django.forms import model_to_dict
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import PermissionDenied

from ansible_base.lib.utils.db import ensure_transaction
from ansible_base.lib.utils.models import is_add_perm
from ansible_base.rbac.models import RoleDefinition
from ansible_base.rbac.permission_registry import permission_registry

logger = logging.getLogger(__name__)


def required_related_permission(field: Field) -> Optional[str]:
    """Permission level required to change field

    Returns a permission codename like change_inventory.
    """
    parent_field_name = permission_registry.get_parent_fd_name(field.model)
    if field.name == parent_field_name:
        return f'add_{field.model._meta.model_name}'
    rel_cls = field.related_model
    custom_perms = dict(rel_cls._meta.permissions)
    for action in settings.ANSIBLE_BASE_CHECK_RELATED_PERMISSIONS:
        codename = f'{action}_{rel_cls._meta.model_name}'
        if action in rel_cls._meta.default_permissions or codename in custom_perms:
            return codename
    return None


def related_permission_fields(cls):
    for field in cls._meta.concrete_fields:
        if isinstance(field, ForeignKey) and permission_registry.is_registered(field.related_model):
            yield field


def validate_field_data(field_name: str, data: dict):
    if f'{field_name}_id' in data:
        raise RuntimeError(f'Expected model_to_dict format of data, received {data}')
    if field_name in data and isinstance(data[field_name], Model):
        raise RuntimeError(f'Expected primary key for {field_name} but received {data[field_name]}')


def log_related_check(user, cls, errors, checked_fields, unchanged_fields):
    if errors:
        logger.warning(
            f'User {user.pk} lacks {cls._meta.model_name} related permissions, checked {checked_fields}, '
            f'errored: {list(errors.keys())}, unchanged: {unchanged_fields}'
        )
    elif checked_fields:
        logger.info(f'User {user.pk} has {cls._meta.model_name} related permissions {checked_fields}, unchanged: {unchanged_fields}')
    elif unchanged_fields:
        logger.debug(f'User {user.pk} needs no {cls._meta.model_name} related permissions, all fields unchanged: {unchanged_fields}')


def check_related_permissions(user, cls, old_data, new_data):
    """Raise PermissionDenied if user lacks access to changing related item

    Both old_data and new_data represent the properties of an object of cls.
    """
    errors = {}
    checked_fields = {}  # only for logging
    unchanged_fields = []  # only for logging

    for field in related_permission_fields(cls):
        # Assure that data structure is expected to avoid giving incorrect evaluations
        validate_field_data(field.name, new_data)
        validate_field_data(field.name, old_data)

        # A permission-relevant field is given in the new data
        if field.name in old_data and old_data.get(field.name) == new_data.get(field.name):
            unchanged_fields.append(field.name)
        else:
            # This field is verified to have changed compared to old data
            to_check = required_related_permission(field)
            if (to_check is None) or (field.null and (new_data.get(field.name) is None) and (not is_add_perm(to_check))):
                # user can null non-parent fields with no additional permission
                continue
            checked_fields[field.name] = to_check
            rel_obj = field.related_model(pk=new_data.get(field.name))
            if not user.has_obj_perm(rel_obj, to_check):
                errors[field.name] = _('You do not have permission to use this object.')

    # It is fairly useful to log the outcome for transparency to the administrator
    log_related_check(user, cls, errors, checked_fields, unchanged_fields)

    if errors:
        raise PermissionDenied(errors)


class RelatedAccessMixin:
    """Class to be used by apps to check permissions to related objects

    This is a core part of integrating permission checks with REST APIs.
    Full enablement of checks is accomplished by this plus
    the permission class.
    """

    def update(self, instance, validated_data):
        """Override DRF ModelSerializer.update method to check permissions

        The super() of this method does setattr on instance with validated_data
        thus, this is our last chance to get a representation of the prior
        object so we know what the user has changed and did not change.

        This runs in a transaction so that PermissionDenied exception will
        roll back changes.
        We have to save the model before we accurately know what the new
        fields are, because model logic can, and will, change things.
        """
        view = self.context.get('view', None)
        if not view or not view.request:
            logger.warning(f'Serializer cannot check related permissions of {self.Meta.model}-{instance.pk} because context was not passed to {type(self)}')
            updated_instance = super().update(instance, validated_data)
        else:
            # Properties of the prior instance must be saved before setattr with new data
            # this is analogous to making a copy of instance
            old_data = model_to_dict(instance)
            with ensure_transaction():
                updated_instance = super().update(instance, validated_data)
                check_related_permissions(view.request.user, self.Meta.model, old_data, model_to_dict(updated_instance))
        return updated_instance

    def create(self, validated_data):
        view = self.context.get('view', None)
        if not view or not view.request:
            logger.warning(f'Serializer cannot check related permissions for new {self.Meta.model} because context was not passed to {type(self)}')
            instance = super().create(validated_data)
        else:
            with ensure_transaction():
                instance = super().create(validated_data)
                check_related_permissions(view.request.user, self.Meta.model, {}, model_to_dict(instance))
                RoleDefinition.objects.give_creator_permissions(view.request.user, instance)
        return instance
