import pytest
from django.contrib.auth.models import AnonymousUser
from django.test.utils import override_settings

from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import RoleDefinition
from ansible_base.rbac.policies import can_change_user, visible_teams, visible_users
from test_app.models import Organization, Team, User


@pytest.mark.django_db
def test_org_admin_can_not_change_superuser(org_admin_rd, organization):
    org_admin = User.objects.create(username='org-admin')
    org_admin_rd.give_permission(org_admin, organization)

    admin = User.objects.create(username='new-superuser', is_superuser=True)
    assert not can_change_user(org_admin, admin)


@pytest.mark.django_db
def test_unrelated_can_not_change_user():
    alice = User.objects.create(username='alice')
    bob = User.objects.create(username='bob')

    for first, second in [(alice, bob), (bob, alice)]:
        assert not can_change_user(first, second)


@pytest.mark.django_db
def test_superuser_can_change_new_user(admin_user):
    alice = User.objects.create(username='alice')
    assert can_change_user(admin_user, alice)


@pytest.mark.django_db
def test_user_can_manage_themselves():
    alice = User.objects.create(username='alice')
    assert can_change_user(alice, alice)


@pytest.mark.django_db
def test_visible_users_anonymous_user():
    User.objects.create(username='alice')
    User.objects.create(username='bob', is_superuser=True)

    qs = visible_users(AnonymousUser())
    assert not qs.exists()


@pytest.mark.django_db
def test_visible_teams_anonymous_user():
    org = Organization.objects.create(name='Test Org')
    Team.objects.create(name='Test Team', organization=org)

    qs = visible_teams(AnonymousUser())
    assert not qs.exists()


@pytest.mark.django_db
def test_visible_teams_superuser(admin_user):
    org1 = Organization.objects.create(name='Org 1')
    org2 = Organization.objects.create(name='Org 2')
    team1 = Team.objects.create(name='Team 1', organization=org1)
    team2 = Team.objects.create(name='Team 2', organization=org2)

    qs = visible_teams(admin_user)
    assert qs.count() == 2
    assert set(qs.values_list('pk', flat=True)) == {team1.pk, team2.pk}


@pytest.mark.django_db
def test_visible_teams_user_with_no_permissions():
    org = Organization.objects.create(name='Test Org')
    Team.objects.create(name='Test Team', organization=org)

    user = User.objects.create(username='regular_user')
    qs = visible_teams(user)
    assert not qs.exists()


@pytest.mark.django_db
def test_visible_teams_user_with_view_permission_on_one_org():
    org1 = Organization.objects.create(name='Org 1')
    org2 = Organization.objects.create(name='Org 2')
    team1 = Team.objects.create(name='Team 1', organization=org1)
    team2 = Team.objects.create(name='Team 2', organization=org2)

    user = User.objects.create(username='viewer')
    view_org_rd = RoleDefinition.objects.create_from_permissions(
        permissions=['view_organization'],
        name='view-org-rd',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
    )
    view_org_rd.give_permission(user, org1)

    qs = visible_teams(user)
    assert qs.count() == 1
    assert qs.first().pk == team1.pk
    assert team2.pk not in qs.values_list('pk', flat=True)


@pytest.mark.django_db
def test_visible_teams_user_with_view_permission_on_multiple_orgs():
    org1 = Organization.objects.create(name='Org 1')
    org2 = Organization.objects.create(name='Org 2')
    org3 = Organization.objects.create(name='Org 3')
    team1 = Team.objects.create(name='Team 1', organization=org1)
    team2 = Team.objects.create(name='Team 2', organization=org2)
    team3 = Team.objects.create(name='Team 3', organization=org3)

    user = User.objects.create(username='multi_viewer')
    view_org_rd = RoleDefinition.objects.create_from_permissions(
        permissions=['view_organization'],
        name='view-org-rd',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
    )
    view_org_rd.give_permission(user, org1)
    view_org_rd.give_permission(user, org2)

    qs = visible_teams(user)
    assert qs.count() == 2
    assert set(qs.values_list('pk', flat=True)) == {team1.pk, team2.pk}
    assert team3.pk not in qs.values_list('pk', flat=True)


@pytest.mark.django_db
@pytest.mark.parametrize(
    'user_type,org_admins_can_see_all,expected_team1_count,expected_team2_count',
    [
        # (user_type, org_admins_can_see_all, expected_team1_count, expected_team2_count)
        # user_type: 'superuser', 'org_admin', 'regular_viewer'
        ('superuser', False, 1, 1),  # Superuser sees all teams regardless of setting
        ('superuser', True, 1, 1),  # Superuser sees all teams regardless of setting
        ('org_admin', False, 1, 0),  # Org admin only sees teams in their org when setting is False
        ('org_admin', True, 1, 1),  # Org admin sees all teams when setting is True
        ('regular_viewer', False, 1, 0),  # Regular viewer only sees teams in orgs they can view
        ('regular_viewer', True, 1, 0),  # Setting doesn't affect regular viewers without change permission
    ],
)
def test_visible_teams_with_custom_queryset(user_type, org_admins_can_see_all, expected_team1_count, expected_team2_count, org_admin_rd):
    org1 = Organization.objects.create(name='Org 1')
    org2 = Organization.objects.create(name='Org 2')
    team1 = Team.objects.create(name='Team 1', organization=org1)
    team2 = Team.objects.create(name='Team 2', organization=org2)

    # Create user based on type
    if user_type == 'superuser':
        user = User.objects.create(username='superuser', is_superuser=True)
    elif user_type == 'org_admin':
        user = User.objects.create(username='org-admin')
        org_admin_rd.give_permission(user, org1)
    else:  # regular_viewer
        user = User.objects.create(username='viewer')
        view_org_rd = RoleDefinition.objects.create_from_permissions(
            permissions=['view_organization'],
            name='view-org-rd',
            content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
        )
        view_org_rd.give_permission(user, org1)

    with override_settings(ORG_ADMINS_CAN_SEE_ALL_USERS=org_admins_can_see_all):
        # Test with custom queryset that filters to team1
        custom_qs = Team.objects.filter(name='Team 1')
        qs = visible_teams(user, queryset=custom_qs)
        assert qs.count() == expected_team1_count
        if expected_team1_count > 0:
            assert qs.first().pk == team1.pk

        # Test with custom queryset that filters to team2
        custom_qs = Team.objects.filter(name='Team 2')
        qs = visible_teams(user, queryset=custom_qs)
        assert qs.count() == expected_team2_count
        if expected_team2_count > 0:
            assert qs.first().pk == team2.pk

        # Test with custom queryset that includes both teams
        custom_qs = Team.objects.filter(name__in=['Team 1', 'Team 2'])
        qs = visible_teams(user, queryset=custom_qs)
        assert qs.count() == expected_team1_count + expected_team2_count


@pytest.mark.django_db
def test_visible_teams_org_admin_can_view_all_users_teams(org_admin_rd):
    org1 = Organization.objects.create(name='Org 1')
    org2 = Organization.objects.create(name='Org 2')
    team1 = Team.objects.create(name='Team 1', organization=org1)
    team2 = Team.objects.create(name='Team 2', organization=org2)

    org_admin = User.objects.create(username='org-admin')
    org_admin_rd.give_permission(org_admin, org1)

    # Org admin should see all teams (because can_view_all_users returns True for org admins with change permission)
    # can_view_all_users checks for 'change' permission, and org_admin_rd gives change_organization
    # So can_view_all_users should return True if ORG_ADMINS_CAN_SEE_ALL_USERS is True
    # Test both scenarios
    with override_settings(ORG_ADMINS_CAN_SEE_ALL_USERS=True):
        qs = visible_teams(org_admin)
        assert qs.count() == 2
        assert set(qs.values_list('pk', flat=True)) == {team1.pk, team2.pk}

    with override_settings(ORG_ADMINS_CAN_SEE_ALL_USERS=False):
        qs = visible_teams(org_admin)
        # Should only see teams in org1
        assert qs.count() == 1
        assert qs.first().pk == team1.pk
