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
from django.db.utils import IntegrityError

from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import ObjectRole, RoleDefinition, RoleEvaluation
from test_app.models import Organization


@pytest.mark.django_db
def test_role_definition_name_unique():
    RoleDefinition.objects.create(name='foo')
    with pytest.raises(IntegrityError):
        RoleDefinition.objects.create(name='foo')


@pytest.mark.django_db
def test_object_role_unique_rule():
    org = Organization.objects.create(name='foo')
    rd = RoleDefinition.objects.create(name='foo')
    ObjectRole.objects.create(object_id=org.id, content_type_id=permission_registry.org_ct_id, role_definition=rd)
    with pytest.raises(IntegrityError):
        ObjectRole.objects.create(object_id=org.id, content_type_id=permission_registry.org_ct_id, role_definition=rd)


@pytest.mark.django_db
def test_role_evaluation_unique_rule():
    org = Organization.objects.create(name='foo')
    rd = RoleDefinition.objects.create(name='foo')
    obj_role = ObjectRole.objects.create(role_definition=rd, object_id=org.id, content_type_id=permission_registry.org_ct_id)
    RoleEvaluation.objects.create(codename='view_organization', role=obj_role, object_id=org.id, content_type_id=permission_registry.org_ct_id)
    with pytest.raises(IntegrityError):
        RoleEvaluation.objects.create(codename='view_organization', role=obj_role, object_id=org.id, content_type_id=permission_registry.org_ct_id)
