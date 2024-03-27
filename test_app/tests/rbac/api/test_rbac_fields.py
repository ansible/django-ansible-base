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

import pytest
from django.urls import reverse

from ansible_base.rbac.api.serializers import RoleDefinitionSerializer


@pytest.mark.django_db
def test_invalid_content_type(admin_api_client):
    serializer = RoleDefinitionSerializer(
        data=dict(name='foo-role-def', description='bar', permissions=['aap.view_organization'], content_type='aap.foo_does_not_exist_model')
    )
    assert not serializer.is_valid()
    assert 'object does not exist' in str(serializer.errors['content_type'])
    assert 'permissions' not in serializer.errors


@pytest.mark.django_db
def test_invalid_permission(admin_api_client):
    serializer = RoleDefinitionSerializer(
        data=dict(name='foo-role-def', description='bar', permissions=['aap.view_foohomeosi'], content_type='shared.organization')
    )
    assert not serializer.is_valid()
    assert 'object does not exist' in str(serializer.errors['permissions'])
    assert 'content_type' not in serializer.errors


@pytest.mark.django_db
def test_parity_with_resource_registry(admin_api_client):
    types_resp = admin_api_client.get(reverse("resourcetype-list"))
    assert types_resp.status_code == 200
    res_types = set(r['name'] for r in types_resp.data['results'])

    role_types = admin_api_client.options(reverse("roledefinition-list"))
    role_types = set(item['value'] for item in role_types.data['actions']['POST']['content_type']['choices'])

    # Check the types in both registries
    for type_name in ('shared.organization', 'shared.team'):
        assert type_name in res_types
        assert type_name in role_types
