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
from test_app.models import WeirdPerm


@pytest.fixture
def wp_rd():
    return RoleDefinition.objects.create_from_permissions(
        name='name-key-admin',
        permissions=["I'm a lovely coconut", 'crack', 'change_weirdperm', 'view_weirdperm', 'delete_weirdperm'],
        content_type=ContentType.objects.get_for_model(WeirdPerm),
    )


@pytest.fixture
def weird_obj(organization):
    return WeirdPerm.objects.create(organization=organization)


@pytest.mark.django_db
def test_give_user_permission(user, wp_rd, weird_obj):
    "Give user permission to model with a non-id primary key and do basic evaluations"
    assert not user.has_obj_perm(weird_obj, "I'm a lovely coconut")
    assert not user.has_obj_perm(weird_obj, "change")
    assert not user.has_obj_perm(weird_obj, "crack")
    assert set(WeirdPerm.access_qs(user)) == set()

    wp_rd.give_permission(user, weird_obj)

    assert user.has_obj_perm(weird_obj, "I'm a lovely coconut")
    assert user.has_obj_perm(weird_obj, "change")
    assert user.has_obj_perm(weird_obj, "crack")
    assert set(WeirdPerm.access_qs(user)) == set([weird_obj])


@pytest.mark.django_db
def test_make_non_id_api_assignment(admin_api_client, wp_rd, weird_obj, user):
    url = reverse('roleuserassignment-list')
    data = dict(role_definition=wp_rd.id, user=user.id, content_type='aap.weirdperm', object_id=weird_obj.id)
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 201, response.data

    assert user.has_obj_perm(weird_obj, "I'm a lovely coconut")
    assert user.has_obj_perm(weird_obj, "crack")
    assert set(WeirdPerm.access_qs(user)) == set([weird_obj])
