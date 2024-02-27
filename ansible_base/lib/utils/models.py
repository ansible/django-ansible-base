import logging
from itertools import chain

from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from inflection import underscore

from ansible_base.lib.utils.settings import get_setting

logger = logging.getLogger('ansible_base.lib.utils.models.py')


def get_all_field_names(model):
    # Implements compatibility with _meta.get_all_field_names
    # See: https://docs.djangoproject.com/en/1.11/ref/models/meta/#migrating-from-the-old-api
    return list(
        set(
            chain.from_iterable(
                (field.name, field.attname) if hasattr(field, 'attname') else (field.name,)
                for field in model._meta.get_fields()
                # For complete backwards compatibility, you may want to exclude
                # GenericForeignKey from the results.
                if not (field.many_to_one and field.related_model is None)
            )
        )
    )


def get_type_for_model(model):
    """
    Return type name for a given model class.
    """
    opts = model._meta.concrete_model._meta
    return underscore(opts.object_name)


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


def get_system_user():
    system_user = None
    setting_name = 'SYSTEM_USERNAME'
    system_username = get_setting(setting_name)
    system_user = get_user_model().objects.filter(username=system_username).first()
    if system_username is not None and system_user is None:
        logger.error(
            _(
                "{setting_name} is set to {system_username} but no user with that username exists.".format(
                    setting_name=setting_name, system_username=system_username
                )
            )
        )
    return system_user
