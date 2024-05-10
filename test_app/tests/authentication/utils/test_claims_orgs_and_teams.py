import random
import string
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model

from ansible_base.authentication.utils.claims import (
    ReconcileUser,
    create_missing_orgs,
    create_missing_teams,
    create_orgs_and_teams,
    load_existing_orgs,
    load_existing_teams,
    process_organization_and_team_memberships,
)
from ansible_base.lib.utils.auth import get_organization_model, get_team_model
from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import RoleDefinition


def generate_org_or_team_name():
    return ''.join(random.choice(string.ascii_lowercase) for _ in range(10))


@patch('ansible_base.authentication.utils.claims.create_orgs_and_teams')
def test_process_organization_and_team_memberships(mock_create_orgs_and_teams):
    results = {
        'claims': {
            'organization_membership': {},
            'team_membership': {},
        }
    }
    process_organization_and_team_memberships(results)
    mock_create_orgs_and_teams.assert_called_once()


@patch('ansible_base.authentication.utils.claims.load_existing_orgs')
@patch('ansible_base.authentication.utils.claims.create_missing_orgs')
@patch('ansible_base.authentication.utils.claims.load_existing_teams')
@patch('ansible_base.authentication.utils.claims.create_missing_teams')
def test_create_orgs_and_teams(mock_load_existing_orgs, mock_create_missing_orgs, mock_load_existing_teams, mock_create_missing_teams):
    org_list = []
    team_map = {}
    create_orgs_and_teams(org_list, team_map)

    mock_load_existing_orgs.assert_called_once()
    mock_create_missing_orgs.assert_called_once()
    mock_load_existing_teams.assert_called_once()
    mock_create_missing_teams.assert_called_once()


@pytest.mark.django_db
def test_load_existing_orgs():
    Organization = get_organization_model()
    org_names = [generate_org_or_team_name() for x in range(0, 5)]
    orgs = [Organization.objects.get_or_create(name=x)[0] for x in org_names]

    filtered_orgs = orgs[1:]
    filtered_org_names = [x.name for x in filtered_orgs]
    res = load_existing_orgs(filtered_org_names)
    for org in orgs:
        if org in filtered_orgs:
            assert org.name in res
            assert res[org.name] == org.id
        else:
            assert org.name not in res


@pytest.mark.django_db
def test_load_existing_teams():
    Organization = get_organization_model()
    Team = get_team_model()
    org, _ = Organization.objects.get_or_create(name=generate_org_or_team_name())
    team_names = [generate_org_or_team_name() for x in range(0, 5)]
    teams = [Team.objects.get_or_create(name=x, organization=org)[0] for x in team_names]

    filtered_teams = teams[1:]
    filtered_team_names = [x.name for x in filtered_teams]
    res = load_existing_teams(filtered_team_names)
    for team in teams:
        if team in filtered_teams:
            assert team.name in res
        else:
            assert team.name not in res


@pytest.mark.django_db
def test_create_missing_orgs():
    Organization = get_organization_model()
    org_name = generate_org_or_team_name()
    existing_orgs = {}
    create_missing_orgs([org_name], existing_orgs)
    assert org_name in existing_orgs
    assert Organization.objects.filter(name=org_name).exists()


@pytest.mark.django_db
def test_create_missing_teams():
    Organization = get_organization_model()
    Team = get_team_model()

    org_name = generate_org_or_team_name()
    org, _ = Organization.objects.get_or_create(name=org_name)
    team_name = generate_org_or_team_name()
    team_map = {team_name: org_name}
    existing_orgs = {org_name: org.id}

    create_missing_teams([team_name], team_map, existing_orgs, [])

    assert Team.objects.filter(name=team_name, organization=org).exists()


@pytest.mark.django_db
def test_reconcile_user_claims():
    Organization = get_organization_model()
    Team = get_team_model()
    User = get_user_model()

    org_name = generate_org_or_team_name()
    org, _ = Organization.objects.get_or_create(name=org_name)
    team_name = generate_org_or_team_name()
    team, _ = Team.objects.get_or_create(name=team_name, organization=org)

    user_name = generate_org_or_team_name()
    user, _ = User.objects.get_or_create(username=user_name)

    # FIXME - test_app doesn't have organizaiton-member or team-member roles?
    RoleDefinition.objects.create_from_permissions(
        permissions=['view_organization', 'member_organization'],
        name='organization-member',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
        managed=True,
    )
    RoleDefinition.objects.create_from_permissions(
        permissions=['view_team', 'member_team'],
        name='team-member',
        content_type=permission_registry.content_type_model.objects.get_for_model(Team),
        managed=True,
    )

    # make the User.authenticator_user.claims property ...
    authenticator_user = MagicMock()
    authenticator_user.claims = {
        'organization_membership': {org_name: True},
        'team_membership': {org_name: {team_name: True}},
    }

    # enable object creation ...
    authenticator_user.provider = MagicMock()
    authenticator_user.provider.create_objects = True

    # do the reconciliation ...
    ReconcileUser.reconcile_user_claims(user, authenticator_user)

    # refresh objects ...
    org.refresh_from_db()
    team.refresh_from_db()

    # now check that the org includes the user ...
    assert org.users.filter(pk=user.pk).exists()

    # now check that the team includes the user ...
    assert team.users.filter(pk=user.pk).exists()
