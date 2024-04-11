from django.contrib.auth import get_user_model

from ansible_base.authentication.models import Authenticator
from ansible_base.resource_registry.registry import ResourceConfig, ServiceAPIConfig, SharedResource
from ansible_base.resource_registry.shared_types import OrganizationType, TeamType, UserType
from ansible_base.resource_registry.utils.resource_type_processor import ResourceTypeProcessor
from test_app.models import Organization, Original1, Proxy2, ResourceMigrationTestModel, Team


class UserProcessor(ResourceTypeProcessor):
    def pre_serialize_additional(self):
        # These fields aren't supported in TestApp, so we'll set them to blank
        setattr(self.instance, "external_auth_provider", None)
        setattr(self.instance, "external_auth_uid", None)
        setattr(self.instance, "organizations", [])
        setattr(self.instance, "organizations_administered", [])

        return self.instance


class APIConfig(ServiceAPIConfig):
    custom_resource_processors = {"shared.user": UserProcessor}
    service_type = "aap"


RESOURCE_LIST = [
    ResourceConfig(
        get_user_model(),
        shared_resource=SharedResource(serializer=UserType, is_provider=False),
        name_field="username",
    ),
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
    ResourceConfig(Original1),
    ResourceConfig(Proxy2),
]
