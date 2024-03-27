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
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from ansible_base.rbac.models import RoleDefinition
from test_app.models import PositionModel


@pytest.fixture
def nk_rd():
    return RoleDefinition.objects.create_from_permissions(
        name='name-key-admin',
        permissions=['change_positionmodel', 'view_positionmodel', 'delete_positionmodel'],
        content_type=ContentType.objects.get_for_model(PositionModel),
    )


@pytest.fixture
def position(organization):
    return PositionModel.objects.create(position=4, organization=organization)


@pytest.mark.django_db
def test_give_user_permission(user, nk_rd, position):
    "Give user permission to model with a non-id primary key and do basic evaluations"
    assert not user.has_obj_perm(position, 'change')
    assert set(PositionModel.access_qs(user)) == set()

    nk_rd.give_permission(user, position)

    assert user.has_obj_perm(position, 'change')
    assert set(PositionModel.access_qs(user)) == set([position])


@pytest.mark.django_db
def test_make_non_id_api_assignment(admin_api_client, nk_rd, position, user):
    url = reverse('roleuserassignment-list')
    data = dict(role_definition=nk_rd.id, user=user.id, content_type='aap.positionmodel', object_id=position.position)
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 201, response.data

    assert user.has_obj_perm(position, 'change')
    assert set(PositionModel.access_qs(user)) == set([position])
