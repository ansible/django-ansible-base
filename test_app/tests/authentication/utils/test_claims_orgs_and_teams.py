import random
import string
from unittest.mock import MagicMock

import pytest
from django.contrib.auth import get_user_model

from ansible_base.authentication.utils.claims import ReconcileUser, process_organization_and_team_memberships
from ansible_base.lib.utils.auth import get_organization_model, get_team_model
from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import RoleDefinition


def generate_org_or_team_name():
    return ''.join(random.choice(string.ascii_lowercase) for _ in range(10))


@pytest.mark.django_db
def test_process_organization_and_team_memberships():
    Organization = get_organization_model()
    Team = get_team_model()

    results = {
        'claims': {
            'organization_membership': {'foo-org': True, 'foo-org-two': False},
            'team_membership': {'foo-org': {'foo-team': True, 'foo-team-two': False}},
        }
    }
    process_organization_and_team_memberships(results)

    assert Organization.objects.filter(name='foo-org').exists()
    assert not Organization.objects.filter(name='foo-org-two').exists()

    org = Organization.objects.get(name='foo-org')
    assert Team.objects.filter(name='foo-team', organization=org).exists()
    assert not Team.objects.filter(name='foo-team-two', organization=org).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("create_objects", [True, False])
def test_reconcile_user_claims(create_objects):
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
    authenticator_user.provider.create_objects = create_objects

    # do the reconciliation ...
    ReconcileUser.reconcile_user_claims(user, authenticator_user)

    # refresh objects ...
    org.refresh_from_db()
    team.refresh_from_db()

    # now check that the org includes the user ...
    assert org.users.filter(pk=user.pk).exists()
    # now check that the team includes the user ...
    assert team.users.filter(pk=user.pk).exists()


@pytest.mark.django_db
def test_reconcile_user_claims_with_no_org_or_team():
    """Make sure reconciliation skips missing orgs&teams."""
    Organization = get_organization_model()
    Team = get_team_model()
    User = get_user_model()

    # define these but do not create them ...
    org_name = generate_org_or_team_name()
    team_name = generate_org_or_team_name()

    user_name = generate_org_or_team_name()
    user, _ = User.objects.get_or_create(username=user_name)

    # make the User.authenticator_user.claims property ...
    authenticator_user = MagicMock()
    authenticator_user.claims = {
        'organization_membership': {org_name: True},
        'team_membership': {org_name: {team_name: True}},
    }

    # enable object creation ...
    authenticator_user.provider = MagicMock()
    authenticator_user.provider.create_objects = False

    # do the reconciliation ...
    ReconcileUser.reconcile_user_claims(user, authenticator_user)

    # ensure the org does not exist ...
    assert not Organization.objects.filter(name=org_name).exists()

    # ensure the team does not exist ...
    assert not Team.objects.filter(name=team_name).exists()
