from typing import Any, Type, Union
from uuid import UUID

from django.apps import apps as django_apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.db.models import CharField, Model, OuterRef
from django.db.models.functions import Cast
from django.db.models.query import QuerySet

from ansible_base.lib.abstract_models.organization import AbstractOrganization
from ansible_base.lib.abstract_models.team import AbstractTeam


def get_model_from_settings(setting_name: str) -> Any:
    """
    Return the User model that is active in this project.
    """
    try:
        setting = getattr(settings, setting_name)
    except AttributeError:
        raise ImproperlyConfigured(f"{setting_name} is not defined in settings.")
    try:
        return django_apps.get_model(setting, require_ready=False)
    except ValueError:
        raise ImproperlyConfigured(f"{setting_name} must be of the form 'app_label.model_name'")
    except LookupError:
        raise ImproperlyConfigured(f"{setting_name} refers to model '{setting}' that has not been installed")


def get_team_model() -> Type[AbstractTeam]:
    return get_model_from_settings('ANSIBLE_BASE_TEAM_MODEL')


def get_organization_model() -> Type[AbstractOrganization]:
    return get_model_from_settings('ANSIBLE_BASE_ORGANIZATION_MODEL')


def get_object_by_ansible_id(qs: QuerySet, ansible_id: Union[str, UUID], annotate_as: str = 'ansible_id_for_filter') -> Model:
    resource_cls = django_apps.get_model('dab_resource_registry', 'Resource')
    content_type_cls = django_apps.get_model('contenttypes', 'ContentType')
    cls = qs.model
    ct = content_type_cls.objects.get_for_model(cls)
    pk_field_name = cls._meta.pk.name
    pk_reference = Cast(OuterRef(pk_field_name), output_field=CharField())
    resource_qs = resource_cls.objects.filter(object_id=pk_reference, content_type=ct).values('ansible_id')
    return qs.annotate(**{annotate_as: resource_qs}).get(**{annotate_as: ansible_id})


def get_user_by_ansible_id(ansible_id: Union[str, UUID], annotate_as: str = 'ansible_id_for_filter') -> Model:
    return get_object_by_ansible_id(get_user_model().objects.all(), ansible_id, annotate_as=annotate_as)
