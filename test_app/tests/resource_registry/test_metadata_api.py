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

from django.urls import reverse

from ansible_base.resource_registry.models import service_id


def test_service_metadata(admin_api_client):
    """Test that the resource list is working."""
    url = reverse("service-metadata")
    resp = admin_api_client.get(url)

    assert resp.status_code == 200
    assert resp.data["service_type"] == "aap"
    assert resp.data["service_id"] == service_id()
