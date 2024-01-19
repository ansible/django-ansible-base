from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from ansible_base.models import Authenticator
from ansible_base.resource_registry import ResourceConfig, ServiceAPIConfig, SharedResource, TeamType, UserType


class APIConfig(ServiceAPIConfig):
    service_type = "aap"


RESOURCE_LIST = (
    ResourceConfig(get_user_model(), shared_resource=SharedResource(serializer=UserType, is_provider=True), name_field="username"),
    ResourceConfig(
        Group,
        shared_resource=SharedResource(serializer=TeamType, is_provider=True),
    ),
    ResourceConfig(Authenticator),
)
