import logging
from dataclasses import asdict, dataclass
from itertools import chain
from typing import Optional, Tuple

from crum import get_current_user
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser
from django.db.models import Model
from django.utils.translation import gettext_lazy as _
from inflection import underscore

from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from ansible_base.lib.utils.settings import get_setting
from ansible_base.lib.utils.string import make_json_safe

logger = logging.getLogger('ansible_base.lib.utils.models')


def get_all_field_names(model, concrete_only=False, include_attnames=True):
    # Implements compatibility with _meta.get_all_field_names
    # See: https://docs.djangoproject.com/en/1.11/ref/models/meta/#migrating-from-the-old-api
    return list(
        set(
            chain.from_iterable(
                (field.name, field.attname) if include_attnames and hasattr(field, 'attname') else (field.name,)
                for field in model._meta.get_fields()
                # For complete backwards compatibility, you may want to exclude
                # GenericForeignKey from the results.
                if not (field.many_to_one and field.related_model is None) and not (concrete_only and not field.concrete)
            )
        )
    )


def get_type_for_model(model):
    """
    Return type name for a given model class.
    """
    opts = model._meta.concrete_model._meta
    return underscore(opts.object_name)


def is_add_perm(codename: str) -> bool:
    """Utility method to say whether codename represents adding permission.

    This type of permission requires special treatment in several places
    in DAB RBAC because the permission defers to the parent object.
    Although the function is trivial, this standardizes the criteria.
    """
    use_codename = codename
    if codename.count('.') == 1:
        _, use_codename = codename.split('.')
    return use_codename.startswith('add_')


def prevent_search(relation):
    """
    Used to mark a model field or relation as "restricted from filtering"
    e.g.,

    class AuthToken(BaseModel):
        user = prevent_search(models.ForeignKey(...))
        sensitive_data = prevent_search(models.CharField(...))

    The flag set by this function is used by
    `ansible_base.rest_filters.rest_framework.field_lookup_backend.FieldLookupBackend` to block fields and relations that
    should not be searchable/filterable via search query params
    """
    setattr(relation, '__prevent_search__', True)
    return relation


def user_summary_fields(user):
    sf = {}
    for field_name in ('id', 'username', 'first_name', 'last_name'):
        sf[field_name] = getattr(user, field_name)
    return sf


def is_system_user(user: Optional[AbstractUser]) -> bool:
    """
    Takes a user objects and returns a boolean if that user's username is the same as the SYSTEM_USERNAME
    """
    system_username = get_system_username()[0]
    if system_username is None or user is None:
        return False
    return user.username == system_username


def get_system_user() -> Optional[AbstractUser]:
    system_username, setting_name = get_system_username()
    system_user = get_user_model().objects.filter(username=system_username).first()
    logger.error(f"Got system user {system_user} for {system_username}")
    # We are using a global variable to try and track if this thread has already spit out the message, if so ignore
    logger.error(f"{system_username is not None} {system_user is None}")
    if system_username is not None and system_user is None:
        logger.error("HERE")
        logger.error(
            _(
                "{setting_name} is set to {system_username} but no user with that username exists.".format(
                    setting_name=setting_name, system_username=system_username
                )
            )
        )
        system_user = create_system_user()
        logger.error(f"Create system user returned {system_user}")
    logger.error(f"Returning {system_user}")
    return system_user


def get_system_username() -> Tuple[Optional[str], str]:
    # Returns (system_username, setting_name)
    setting_name = 'SYSTEM_USERNAME'
    return get_setting(setting_name), setting_name


def create_system_user() -> AbstractUser:
    #
    # Creating a system user using ORM is near impossible because it needs to reference itself for created/modified _by
    #

    system_user = get_user_model().objects.create(username=get_system_username()[0], is_active=False, modified_by=None, created_by=None)
    if hasattr(get_user_model(), 'managed'):
        system_user.managed = True
    system_user.created_by = system_user
    system_user.save()
    system_user.refresh_from_db()

    #    # Build our own user but do not call save
    #    system_user = get_user_model()(username=get_system_username()[0], is_active=False)
    #    system_user.set_unusable_password()
    #    if hasattr(get_user_model(), 'managed'):
    #        system_user.managed = True
    #
    #    # Generate the SQL queries through the ORM
    #    from django.db import connection
    #    from django.db.models import sql
    #
    #    values = system_user._meta.local_fields[1:]
    #    query = sql.InsertQuery(system_user)
    #    query.insert_values(values, [system_user])
    #    compiler = query.get_compiler('default')
    #    statements = compiler.as_sql()
    #
    #    # Do one last check to make sure someone didn't sneak in on us....
    #    system_user = get_user_model().objects.filter(username=get_system_username()[0]).first()
    #
    #    if not system_user:
    #        # Execute the insert statement to create the user without calling save
    #        with connection.cursor() as cursor:
    #            for statement in statements:
    #                cursor.execute(statement[0], statement[1])
    #
    #        # Reload the user object from the DB "formally"
    #        system_user = get_user_model().objects.get(username=get_system_username()[0])
    #
    #        logger.info(f"Created system user {system_user.username} as {system_user.pk}")
    #
    #        # Update the system user created/modified _by
    #        system_user.created_by = system_user
    #        system_user.modified_by = system_user
    #
    #        values = system_user._meta.local_fields
    #        query = sql.UpdateQuery(system_user)
    #        query.add_related_update(system_user, 'modified_by', system_user)
    #        query.add_update_values(
    #            {
    #                'created_by': system_user,
    #                'modified_by': system_user,
    #            }
    #        )
    #        compiler = query.get_compiler('default')
    #        statements = compiler.as_sql()
    #
    #        # Execute the insert statement to create the user without calling save
    #        with connection.cursor() as cursor:
    #            cursor.execute(statements[0], statements[1])
    #
    #        system_user.refresh_from_db()

    return system_user


def current_user_or_system_user() -> Optional[AbstractUser]:
    """
    Attempt to get the current user. If there is none or it is anonymous,
    try to return the system user instead.
    """
    user = get_current_user()
    if user is None or user.is_anonymous:
        user = get_system_user()
    return user


def is_encrypted_field(model, field_name):
    if model is None:
        return False

    if issubclass(model, AbstractUser) and field_name == 'password':
        return True

    # This throws FieldDoesNotExist if the field does not exist, which is reasonable here, so we don't catch it
    field = model._meta.get_field(field_name)
    if getattr(field, '__prevent_search__', False):
        return True

    return field_name in getattr(model, 'encrypted_fields', [])


@dataclass
class ModelDiff:
    added_fields: dict
    removed_fields: dict
    changed_fields: dict

    def __bool__(self):
        return bool(self.added_fields or self.removed_fields or self.changed_fields)

    @property
    def has_changes(self):
        return bool(self)

    dict = asdict


def diff(
    old,
    new,
    require_type_match=True,
    json_safe=True,
    include_m2m=False,
    exclude_fields=[],
    limit_fields=[],
    sanitize_encrypted=True,
    all_values_as_strings=False,
):
    """
    Diff two instances of models (which do not have to be the same type of model
    if given require_type_match=False).

    This function is used in particular by the activitystream application where
    the changes returned by this function are stored as models change.

    :param old: The old instance for comparison
    :param new: The new instance for comparison
    :param require_type_match: If True, old and new must be of the same type of
        model. (default: True)
    :param json_safe: If True, the diff will be made JSON-safe by converting
        all non-JSON-safe values to strings using Django's smart_str function.
        (default: True)
    :param include_m2m: If True, include many-to-many fields in the diff.
        Otherwise, they are ignored. (default: False)
    :param exclude_fields: A list of field names to exclude from the diff.
        (default: [])
    :param limit_fields: A list of field names to limit the diff to. This can be
        useful, for example, when update_fields is passed to a model's save
        method and you only want to diff the fields that were updated.
        (default: [])
    :param sanitize_encrypted: If True, encrypted fields will be replaced with
        a constant value (ENCRYPTED_STRING) in the diff. (default: True)
    :param all_values_as_strings: If True, all values will be converted to
        strings after diffing, using Field.value_to_string. (default: False)
    :return: A dictionary with the following
        - added_fields: A dictionary of fields that were added between old and
          new. Importantly, if old and new are the same type of model, this
          should always be empty. An "added field" does not mean that the field
          became non-empty, it means that the field was completely absent from
          the old type of model and is now present in the new type of model. If
          this entry is non-empty, it has the form: {"field_name": value} where
          value is the new value of the field.
        - removed_fields: A dictionary of fields that were removed between old
          and new. Similar to added_fields, if old and new are the same type of
          model, this should always be empty. It has the same structure as
          added_fields except the value is the old value of the field.
        - changed_fields: A dictionary of fields that were changed between old
          and new. The key of each entry is the field name, and the value is a
          tuple of the old value and the new value.
    """

    model_diff = ModelDiff(added_fields={}, removed_fields={}, changed_fields={})

    # Short circuit if both objects are None
    if old is None and new is None:
        return model_diff

    # Fail if we are not dealing with None or Model types
    if (old is not None and not isinstance(old, Model)) or (new is not None and not isinstance(new, Model)):
        raise TypeError('old and new must be a Model instance or None')

    # If we have to have matching types and both objects are not None and their types don't match then fail
    if require_type_match and (old is not None and new is not None) and type(old) is not type(new):  # noqa: E721
        raise TypeError('old and new must be of the same type')

    # Extract all of the fields and their values into a dict in the format of:
    #  fields = {
    #     'old': { <field>: <value>, [<field>: <value> ...]},
    #     'new': { <field>: <value>, [<field>: <value> ...]},
    #  }
    fields = {}
    for name, obj in (('old', old), ('new', new)):
        fields[name] = {}
        if obj is None:
            continue

        for field in get_all_field_names(obj, concrete_only=True, include_attnames=False):
            field_obj = obj._meta.get_field(field)

            # Skip the field if needed
            if field in exclude_fields:
                continue
            if limit_fields and field not in limit_fields:
                continue
            if not include_m2m and field_obj.many_to_many:
                continue

            if all_values_as_strings:
                if getattr(obj, field) is None:
                    value = None
                else:
                    value = field_obj.value_to_string(obj)
            elif json_safe:
                value = make_json_safe(getattr(obj, field))
            else:
                value = getattr(obj, field)

            fields[name][field] = value

    old_fields_set = set(fields['old'].keys())
    new_fields_set = set(fields['new'].keys())
    old_model = old.__class__ if old else None
    new_model = new.__class__ if new else None

    # Get any removed fields from the old_fields - new_fields
    for field in old_fields_set - new_fields_set:
        model_diff.removed_fields[field] = ENCRYPTED_STRING if is_encrypted_field(old_model, field) else fields['old'][field]

    # Get any new fields from the new_fields - old_fields
    for field in new_fields_set - old_fields_set:
        model_diff.added_fields[field] = ENCRYPTED_STRING if is_encrypted_field(new_model, field) else fields['new'][field]

    # Find any modified fields from the union of the sets
    for field in new_fields_set & old_fields_set:
        if fields['old'][field] != fields['new'][field]:
            model_diff.changed_fields[field] = (
                ENCRYPTED_STRING if is_encrypted_field(old_model, field) else fields['old'][field],
                ENCRYPTED_STRING if is_encrypted_field(new_model, field) else fields['new'][field],
            )

    return model_diff
