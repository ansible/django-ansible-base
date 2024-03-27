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
from django.contrib.auth.models import Permission

from test_app.models import Inventory, ProxyInventory


@pytest.mark.django_db
def test_inventory_permissions_duplicated():
    "This assures that test_app has more than one model with the same permission"
    view_inv_perms = Permission.objects.filter(codename='view_inventory')
    assert view_inv_perms.count() == 2
    assert set(perm.content_type.model_class() for perm in view_inv_perms) == set([Inventory, ProxyInventory])
