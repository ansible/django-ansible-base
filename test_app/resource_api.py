#  Copyright 2024 Red Hat, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

from django.contrib.auth import get_user_model

from ansible_base.authentication.models import Authenticator
from ansible_base.resource_registry.registry import ResourceConfig, ServiceAPIConfig, SharedResource
from ansible_base.resource_registry.shared_types import OrganizationType, TeamType, UserType
from test_app.models import Organization, Original1, Proxy2, ResourceMigrationTestModel, Team


class APIConfig(ServiceAPIConfig):
    service_type = "aap"


RESOURCE_LIST = (
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
)
