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

from ansible_base.resource_registry.models import Resource


@pytest.mark.django_db
def test_existing_resources_created_in_post_migration():
    """
    Test that resources that existed before the registry was added got
    created successfully.
    """
    assert Resource.objects.filter(name="migration resource", content_type__resource_type__name="aap.resourcemigrationtestmodel").exists()
