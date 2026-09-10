import pytest
from django.apps import apps

from ansible_base.rbac import permission_registry
from ansible_base.rbac.managed import OrganizationMember, managed_role_templates
from ansible_base.rbac.models import DABPermission, RoleDefinition, RoleEvaluation
from ansible_base.rbac.validators import validate_permissions_for_model


@pytest.mark.django_db
def test_courtesy_roles_pass_validation():
    """Because these use migration apps, we can not use normal model code, so we validate in tests"""
    for template_name, cls in managed_role_templates.items():
        if '_base' in template_name:
            continue  # abstract, not intended to be used
        constructor = cls()
        perm_list = []
        for str_perm in constructor.get_permissions(apps):
            if '.' in str_perm:
                perm_list.append(DABPermission.objects.get(api_slug=str_perm))
            else:
                perm_list.append(DABPermission.objects.get(codename=str_perm))
        model_cls = constructor.get_model(apps)
        if model_cls is not None:
            ct = permission_registry.content_type_model.objects.get_for_model(constructor.get_model(apps))
        else:
            ct = None  # system role
        validate_permissions_for_model(perm_list, ct, managed=True)


@pytest.mark.django_db
def test_cow_admin():
    rd = RoleDefinition.objects.managed.cow_admin
    perm_list = [perm.codename for perm in rd.permissions.all()]
    assert set(perm_list) == {'change_cow', 'view_cow', 'delete_cow', 'say_cow'}


@pytest.mark.django_db
def test_cow_mooer():
    rd = RoleDefinition.objects.managed.cow_moo
    perm_list = [perm.codename for perm in rd.permissions.all()]
    assert set(perm_list) == {'view_cow', 'say_cow'}
    assert rd.name == 'Cow Mooer'


@pytest.mark.django_db
def test_create_all_managed_roles():
    "This is a method that may be called in migrations, etc."
    assert not RoleDefinition.objects.filter(name='Cow Mooer').exists()
    permission_registry.create_managed_roles(apps)


@pytest.mark.django_db
def test_org_member_includes_view_team():
    """Organization Member role definition should include view_team permission"""
    rd = RoleDefinition.objects.managed.org_member
    perm_codenames = set(rd.permissions.values_list('codename', flat=True))
    assert 'view_team' in perm_codenames
    assert 'view_organization' in perm_codenames
    assert 'member_organization' in perm_codenames


@pytest.mark.django_db
def test_org_member_can_see_teams_in_org(rando, organization, team, org_member_rd):
    """Organization members should be able to view teams within that organization."""
    Team = permission_registry.team_model
    assert set(RoleEvaluation.accessible_objects(Team, rando, 'view_team')) == set()

    org_member_rd.give_permission(rando, organization)

    assert set(RoleEvaluation.accessible_objects(Team, rando, 'view_team')) == {team}


@pytest.mark.django_db
def test_org_member_cannot_see_teams_in_other_org(rando, organization, team, org_member_rd):
    """Organization members should not see teams from other organizations."""
    from test_app.models import Organization as OrgModel

    Team = permission_registry.team_model
    other_org = OrgModel.objects.create(name='other-org')
    other_team = Team.objects.create(name='other-team', organization=other_org)

    org_member_rd.give_permission(rando, organization)

    visible = set(RoleEvaluation.accessible_objects(Team, rando, 'view_team'))
    assert team in visible
    assert other_team not in visible


@pytest.mark.django_db
def test_org_member_sees_multiple_teams_in_org(rando, organization, org_member_rd):
    """Organization members see all teams in their org, not just one."""
    Team = permission_registry.team_model
    team_a = Team.objects.create(name='team-a', organization=organization)
    team_b = Team.objects.create(name='team-b', organization=organization)
    team_c = Team.objects.create(name='team-c', organization=organization)

    org_member_rd.give_permission(rando, organization)

    visible = set(RoleEvaluation.accessible_objects(Team, rando, 'view_team'))
    assert visible == {team_a, team_b, team_c}


@pytest.mark.django_db
def test_org_member_sees_teams_via_access_qs(rando, organization, team, org_member_rd):
    """Verify the higher-level access_qs API also returns org teams for members."""
    Team = permission_registry.team_model
    assert Team.access_qs(rando).count() == 0

    org_member_rd.give_permission(rando, organization)

    assert team in Team.access_qs(rando)


@pytest.mark.django_db
def test_org_member_new_team_becomes_visible(rando, organization, org_member_rd):
    """Teams created after org membership is granted should also be visible."""
    Team = permission_registry.team_model
    org_member_rd.give_permission(rando, organization)

    new_team = Team.objects.create(name='new-team', organization=organization)

    assert new_team in set(RoleEvaluation.accessible_objects(Team, rando, 'view_team'))


@pytest.mark.django_db
def test_update_perms_adds_view_team_to_existing_role():
    """When create_managed_roles runs with update_perms=True,
    an existing Organization Member role gets view_team added."""
    org_member_rd = RoleDefinition.objects.managed.org_member
    view_team_perm = DABPermission.objects.get(codename='view_team')

    # Simulate a stale role missing view_team
    org_member_rd.permissions.remove(view_team_perm)
    assert 'view_team' not in set(org_member_rd.permissions.values_list('codename', flat=True))

    permission_registry.create_managed_roles(apps, update_perms=True)
    org_member_rd.refresh_from_db()

    assert 'view_team' in set(org_member_rd.permissions.values_list('codename', flat=True))

    RoleDefinition.objects.managed.clear()


@pytest.mark.django_db
def test_org_member_revoke_removes_view_team(rando, organization, team, org_member_rd):
    """Granting then removing org membership should make teams invisible again."""
    Team = permission_registry.team_model
    org_member_rd.give_permission(rando, organization)
    assert team in set(RoleEvaluation.accessible_objects(Team, rando, 'view_team'))

    org_member_rd.remove_permission(rando, organization)
    assert set(RoleEvaluation.accessible_objects(Team, rando, 'view_team')) == set()


@pytest.mark.django_db
def test_update_perms_false_does_not_add_view_team():
    """create_managed_roles with default update_perms=False should not
    add view_team to an existing role that is missing it."""
    org_member_rd = RoleDefinition.objects.managed.org_member
    view_team_perm = DABPermission.objects.get(codename='view_team')

    org_member_rd.permissions.remove(view_team_perm)
    assert 'view_team' not in set(org_member_rd.permissions.values_list('codename', flat=True))

    permission_registry.create_managed_roles(apps)
    org_member_rd.refresh_from_db()

    assert 'view_team' not in set(org_member_rd.permissions.values_list('codename', flat=True))

    # Restore for other tests
    org_member_rd.permissions.add(view_team_perm)
    RoleDefinition.objects.managed.clear()


@pytest.mark.django_db
def test_org_member_constructor_permissions():
    """OrganizationMember.get_permissions returns view_team alongside the base permissions."""
    constructor = OrganizationMember()
    perms = constructor.get_permissions(apps)
    assert 'view_team' in perms
    assert 'view_organization' in perms
    assert 'member_organization' in perms
