from datetime import datetime

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from test_app.models import Organization, Team

User = get_user_model()


@pytest.mark.django_db
def test_organization_model():
    org = Organization.objects.create(name="acme", description="ACME Corp.")

    assert org.name == "acme"
    assert org.description == "ACME Corp."
    assert isinstance(org.created_on, datetime)
    assert org.created_by is None
    assert isinstance(org.modified_on, datetime)
    assert org.modified_by is None


@pytest.mark.django_db
def test_organization_model_unique():
    Organization.objects.create(name="acme", description="ACME Corp.")
    with pytest.raises(IntegrityError):
        Organization.objects.create(name="acme", description="Second ACME Corp.")


@pytest.mark.django_db
def test_organization_model_users():
    user = User.objects.create(username="alice")
    org = Organization.objects.create(name="acme")
    org.users.add(user)

    assert list(user.organizations.all()) == [org]


@pytest.mark.django_db
def test_organization_model_teams():
    team = Team.objects.create(name="red")
    org = Organization.objects.create(name="acme")
    org.teams.add(team)

    assert list(team.organizations.all()) == [org]
