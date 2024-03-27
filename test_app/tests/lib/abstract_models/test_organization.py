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

from datetime import datetime

import pytest
from django.db import IntegrityError

from test_app.models import Organization, Team


@pytest.mark.django_db
def test_organization_model(system_user):
    org = Organization.objects.create(name="acme", description="ACME Corp.")

    assert org.name == "acme"
    assert org.description == "ACME Corp."
    assert isinstance(org.created, datetime)
    assert org.created_by == system_user
    assert isinstance(org.modified, datetime)
    assert org.modified_by == system_user

    # I'm not sure why I have to add a delete in here.
    # If I don't it complains on cleanup that the org is referencing a user id 1 which no longer exists
    org.delete()


@pytest.mark.django_db
def test_organization_model_unique():
    Organization.objects.create(name="acme", description="ACME Corp.")
    with pytest.raises(IntegrityError):
        Organization.objects.create(name="acme", description="Second ACME Corp.")


@pytest.mark.django_db
def test_organization_model_teams():
    org = Organization.objects.create(name="acme")
    team = Team.objects.create(name="red", organization=org)

    assert list(org.teams.all()) == [team]
