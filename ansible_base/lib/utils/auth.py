from collections.abc import Iterator
from typing import Any, Type, Union
from uuid import UUID

from django.apps import apps as django_apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Model
from django.db.models.query import QuerySet

from ansible_base.lib.abstract_models.organization import AbstractOrganization
from ansible_base.lib.abstract_models.team import AbstractTeam

_AUTHENTICATION_CHALLENGES_ATTRIBUTE = "_ansible_base_authentication_challenges"


def _authentication_request_objects(request: Any) -> Iterator[Any]:
    """Return a DRF request and its underlying Django request, when present."""
    yield request

    underlying_request = getattr(request, "_request", None)
    if underlying_request is not None and underlying_request is not request:
        yield underlying_request


def record_authentication_challenge(request: Any, challenge: str) -> None:
    """Record a safe authentication challenge in authenticator evaluation order."""
    for request_object in _authentication_request_objects(request):
        challenges = getattr(request_object, _AUTHENTICATION_CHALLENGES_ATTRIBUTE, None)
        if challenges is None:
            challenges = []
            setattr(request_object, _AUTHENTICATION_CHALLENGES_ATTRIBUTE, challenges)
        challenges.append(challenge)


def get_authentication_challenge(request: Any, default: str | None = None) -> str | None:
    """Return the first safe challenge recorded while authenticating a request."""
    for request_object in _authentication_request_objects(request):
        challenges = getattr(request_object, _AUTHENTICATION_CHALLENGES_ATTRIBUTE, ())
        if challenges:
            return challenges[0]
    return default


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


def get_object_by_ansible_id(qs: QuerySet, ansible_id: Union[str, UUID]) -> Model:
    resource_cls = django_apps.get_model('dab_resource_registry', 'Resource')
    content_type_cls = django_apps.get_model('contenttypes', 'ContentType')
    cls = qs.model
    ct = content_type_cls.objects.get_for_model(cls)
    try:
        object_id = resource_cls.objects.values_list('object_id', flat=True).get(ansible_id=ansible_id, content_type=ct)
    except resource_cls.DoesNotExist:
        raise cls.DoesNotExist(f"{cls.__name__} with ansible_id {ansible_id} does not exist.") from None
    return qs.get(pk=object_id)


def get_user_by_ansible_id(ansible_id: Union[str, UUID]) -> Model:
    return get_object_by_ansible_id(get_user_model().objects.all(), ansible_id)
