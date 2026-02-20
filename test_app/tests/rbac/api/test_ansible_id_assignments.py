from uuid import uuid4

import pytest
from django.contrib.contenttypes.models import ContentType
from django.test import override_settings

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import DABContentType, ObjectRole, RoleEvaluation
from ansible_base.resource_registry.models import Resource
from test_app.models import Organization, Team


@pytest.mark.django_db
def test_user_assignment_ansible_id(admin_api_client, inv_rd, rando, inventory):
    resource = Resource.objects.get(object_id=rando.pk, content_type=ContentType.objects.get_for_model(rando).pk)
    url = get_relative_url('roleuserassignment-list')
    data = dict(role_definition=inv_rd.id, content_type='aap.inventory', user_ansible_id=str(resource.ansible_id), object_id=inventory.id)
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 201, response.data
    assert rando.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
def test_team_assignment_ansible_id(admin_api_client, inv_rd, team, inventory, member_rd, rando):
    member_rd.give_permission(rando, team)
    team_ct = ContentType.objects.get_for_model(team)
    resource = Resource.objects.get(object_id=team.pk, content_type=team_ct.pk)
    url = get_relative_url('roleteamassignment-list')
    data = dict(role_definition=inv_rd.id, content_type='aap.inventory', team_ansible_id=str(resource.ansible_id), object_id=inventory.id)
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 201, response.data

    team_role = ObjectRole.objects.get(object_id=team.id, content_type=DABContentType.objects.get_for_model(team), role_definition=member_rd)
    assert RoleEvaluation.objects.filter(role=team_role, codename='change_inventory', object_id=inventory.id).count() == 1
    assert rando.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
@pytest.mark.parametrize('actor', ['user', 'team'])
def test_assignment_id_validation(admin_api_client, inv_rd, team, inventory, rando, actor):
    if actor == 'user':
        actor_obj = rando
    else:
        actor_obj = team
    resource = Resource.objects.get(object_id=actor_obj.pk, content_type=ContentType.objects.get_for_model(actor_obj).pk)
    url = get_relative_url(f'role{actor}assignment-list')
    test_fields = (actor, f'{actor}_ansible_id')

    # Provide too little data
    data = dict(role_definition=inv_rd.id, content_type='aap.inventory', object_id=inventory.id)
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 400, response.data
    for field_name in test_fields:
        assert 'Provide exactly one of' in str(response.data[field_name])

    # Provide too much data
    data[f'{actor}_ansible_id'] = str(resource.ansible_id)
    data[actor] = actor_obj.id
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 400, response.data
    for field_name in test_fields:
        assert 'Provide exactly one of' in str(response.data[field_name])

    # And we rolled back or did not take the action, right?
    assert not rando.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
def test_object_ansible_id_user(admin_api_client, org_inv_rd, rando, inventory, organization):
    resource = Resource.objects.get(object_id=organization.pk, content_type=ContentType.objects.get_for_model(organization).pk)
    url = get_relative_url('roleuserassignment-list')
    data = dict(role_definition=org_inv_rd.id, user=rando.id, object_ansible_id=str(resource.ansible_id))
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 201, response.data
    assert rando.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
def test_missing_object(admin_api_client, inv_rd, rando):
    url = get_relative_url('roleuserassignment-list')
    data = dict(role_definition=inv_rd.id, user=rando.id)
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 400, response.data
    assert response.data['object_id'] == 'Object must be specified for this role assignment'


@pytest.mark.django_db
def test_invalid_ansible_id(admin_api_client, org_inv_rd, rando):
    url = get_relative_url('roleuserassignment-list')
    bad_ansible_id = f'{uuid4()}'
    data = dict(role_definition=org_inv_rd.id, user=rando.id, object_ansible_id=bad_ansible_id)
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 400, response.data
    assert 'object does not exist' in response.data['object_ansible_id']
    assert bad_ansible_id in response.data['object_ansible_id']


@pytest.mark.django_db
def test_object_ansible_id_bad_type(admin_api_client, inv_rd, rando, organization):
    """If giving object_id, type is implied from role definition.

    When giving ansible_id that no longer holds true, and user can give any type.
    This expects a validation error when the object type does not match the role type.
    """
    resource = Resource.objects.get(object_id=organization.pk, content_type=ContentType.objects.get_for_model(organization).pk)
    url = get_relative_url('roleuserassignment-list')
    data = dict(role_definition=inv_rd.id, user=rando.id, object_ansible_id=str(resource.ansible_id))
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 400, response.data
    assert 'organization does not match role type of inventory' in str(response.data['object_ansible_id'])


@pytest.mark.django_db
@override_settings(ALLOW_LOCAL_ASSIGNING_JWT_ROLES=True)
@pytest.mark.parametrize('org_admins_can_see_all_users', [True, False])
def test_get_by_ansible_id_team_object_org_admins_can_see_all_users(
    user,
    user_api_client,
    organization,
    org_admin_rd,
    member_rd,
    admin_rd,
    org_admins_can_see_all_users,
):
    """get_by_ansible_id uses visible_teams for team objects; ORG_ADMINS_CAN_SEE_ALL_USERS controls whether org admins see all teams.

    When creating a RoleTeamAssignment with object_ansible_id pointing to a team in another org:
    - ORG_ADMINS_CAN_SEE_ALL_USERS=False: team not in visible_teams → ValidationError (object does not exist)
    - ORG_ADMINS_CAN_SEE_ALL_USERS=True: team in visible_teams → resolution succeeds (and assignment succeeds if user has change on that team)
    """
    org_admin_rd.give_permission(user, organization)
    actor_team = Team.objects.create(name='actor-team', organization=organization)
    other_org = Organization.objects.create(name='other-org')
    target_team = Team.objects.create(name='target-team', organization=other_org)

    target_team_ct = ContentType.objects.get_for_model(target_team)
    target_team_resource = Resource.objects.get(object_id=target_team.pk, content_type=target_team_ct.pk)

    url = get_relative_url('roleteamassignment-list')
    data = {
        'role_definition': member_rd.id,
        'team': actor_team.id,
        'object_ansible_id': str(target_team_resource.ansible_id),
    }

    if org_admins_can_see_all_users:
        admin_rd.give_permission(user, target_team)

    with override_settings(ORG_ADMINS_CAN_SEE_ALL_USERS=org_admins_can_see_all_users):
        response = user_api_client.post(url, data=data, format='json')

    if org_admins_can_see_all_users:
        assert response.status_code == 201, response.data
    else:
        assert response.status_code == 400, response.data
        assert 'object does not exist' in str(response.data.get('object_ansible_id', []))
