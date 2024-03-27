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
from django.test import override_settings


@pytest.mark.django_db
@override_settings(ANSIBLE_BASE_CACHE_PARENT_PERMISSIONS=False)
def test_parent_permissions_not_cached(rando, organization, org_inv_rd, inventory):
    org_inv_rd.give_permission(rando, organization)
    assert rando.has_obj_perm(inventory, 'change_inventory')
    assert not rando.has_obj_perm(organization, 'change_inventory')


@pytest.mark.django_db
@override_settings(ANSIBLE_BASE_CACHE_PARENT_PERMISSIONS=True)
def test_parent_permissions_cached(rando, organization, org_inv_rd, inventory):
    org_inv_rd.give_permission(rando, organization)
    assert rando.has_obj_perm(inventory, 'change_inventory')
    assert rando.has_obj_perm(organization, 'change_inventory')
