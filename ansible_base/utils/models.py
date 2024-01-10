from itertools import chain

from django.apps import apps as django_apps
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext as _
from inflection import underscore

from ansible_base.utils.settings import get_setting


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
    `ansible_base.filters.rest_framework.field_lookup_backend.FieldLookupBackend` to block fields and relations that
    should not be searchable/filterable via search query params
    """
    setattr(relation, '__prevent_search__', True)
    return relation


def get_organization_model():
    setting = 'ANSIBLE_BASE_ORGANIZATION_MODEL'
    org_model = get_setting(setting, '.Organization')
    try:
        return django_apps.get_model(org_model, require_ready=False)
    except ValueError:
        raise ImproperlyConfigured(_(f"{setting} must be of the form 'app_label.model_name', got {org_model}"))
    except LookupError:
        raise ImproperlyConfigured(_(f"{setting} refers to model '{org_model}' that has not been installed"))
