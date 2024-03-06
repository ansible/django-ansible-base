from django.contrib.auth import get_user_model

from ansible_base.authentication.models import Authenticator
from ansible_base.resource_registry.registry import ResourceConfig, ServiceAPIConfig, SharedResource
from ansible_base.resource_registry.shared_types import OrganizationType, TeamType, UserType
from test_app.models import Organization, ResourceMigrationTestModel, Team


class APIConfig(ServiceAPIConfig):
    service_type = "aap"


RESOURCE_LIST = (
    ResourceConfig(get_user_model(), shared_resource=SharedResource(serializer=UserType, is_provider=False), name_field="username"),
    ResourceConfig(
        Team,
        shared_resource=SharedResource(serializer=TeamType, is_provider=False),
    ),
    ResourceConfig(
        Organization,
        shared_resource=SharedResource(serializer=OrganizationType, is_provider=False),
    ),
    # Authenticators won't be a shared resource in production, but it's a convenient model to use for testing.
    ResourceConfig(Authenticator),
    ResourceConfig(ResourceMigrationTestModel),
)
