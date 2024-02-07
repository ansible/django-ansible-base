from datetime import datetime

import pytest
from django.db import IntegrityError

from test_app.models import Organization, Team


@pytest.mark.django_db
def test_organization_model(system_user):
    org = Organization.objects.create(name="acme", description="ACME Corp.")

    assert org.name == "acme"
    assert org.description == "ACME Corp."
    assert isinstance(org.created_on, datetime)
    assert org.created_by == system_user
    assert isinstance(org.modified_on, datetime)
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
