from uuid import uuid4

import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from ansible_base.rbac.models import ObjectRole, RoleEvaluation
from ansible_base.resource_registry.models import Resource


@pytest.mark.django_db
def test_assignment_attaches_resource(user, organization, org_admin_rd, admin_api_client):
    assignment = org_admin_rd.give_permission(user, organization)
    assert assignment.resource == organization.resource
    assert assignment.object_role.resource == organization.resource

    url = reverse('roleuserassignment-list')
    # Prove that we can filter assignments using ansible_id
    response = admin_api_client.get(url, data={'resource__ansible_id': organization.resource.ansible_id})
    assert response.data['count'] == 1
    # Prove the null case for filtering
    response = admin_api_client.get(url, data={'resource__ansible_id': str(uuid4())})
    assert response.data['count'] == 0


@pytest.mark.django_db
def test_user_assignment_resource(admin_api_client, inv_rd, rando, inventory):
    resource = Resource.objects.get(object_id=rando.pk, content_type=ContentType.objects.get_for_model(rando).pk)
    url = reverse('roleuserassignment-list')
    data = dict(role_definition=inv_rd.id, content_type='aap.inventory', user_resource=str(resource.ansible_id), object_id=inventory.id)
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 201, response.data
    assert rando.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
def test_team_assignment_resource(admin_api_client, inv_rd, team, inventory, member_rd, rando):
    member_rd.give_permission(rando, team)
    team_ct = ContentType.objects.get_for_model(team)
    resource = Resource.objects.get(object_id=team.pk, content_type=team_ct.pk)
    url = reverse('roleteamassignment-list')
    data = dict(role_definition=inv_rd.id, content_type='aap.inventory', team_resource=str(resource.ansible_id), object_id=inventory.id)
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 201, response.data

    team_role = ObjectRole.objects.get(object_id=team.id, content_type=team_ct, role_definition=member_rd)
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
    url = reverse(f'role{actor}assignment-list')
    test_fields = (actor, f'{actor}_resource')

    # Provide too little data
    data = dict(role_definition=inv_rd.id, content_type='aap.inventory', object_id=inventory.id)
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 400, response.data
    for field_name in test_fields:
        assert 'Provide exactly one of' in str(response.data[field_name])

    # Provide too much data
    data[f'{actor}_resource'] = str(resource.ansible_id)
    data[actor] = actor_obj.id
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 400, response.data
    for field_name in test_fields:
        assert 'Provide exactly one of' in str(response.data[field_name])

    # And we rolled back or did not take the action, right?
    assert not rando.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
def test_user_assignment_by_resource(admin_api_client, org_inv_rd, rando, inventory, organization):
    resource = Resource.objects.get(object_id=organization.pk, content_type=ContentType.objects.get_for_model(organization).pk)
    url = reverse('roleuserassignment-list')
    data = dict(role_definition=org_inv_rd.id, user=rando.id, resource=str(resource.ansible_id))
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 201, response.data
    assert rando.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
def test_missing_object(admin_api_client, inv_rd, rando):
    url = reverse('roleuserassignment-list')
    data = dict(role_definition=inv_rd.id, user=rando.id)
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 400, response.data
    assert response.data['object_id'] == 'Object must be specified for this role assignment'


@pytest.mark.django_db
def test_invalid_resource(admin_api_client, org_inv_rd, rando):
    url = reverse('roleuserassignment-list')
    bad_ansible_id = f'{uuid4()}'
    data = dict(role_definition=org_inv_rd.id, user=rando.id, resource=bad_ansible_id)
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 400, response.data
    assert 'does not exist' in str(response.data['resource'])
    assert bad_ansible_id in str(response.data['resource'])


@pytest.mark.django_db
def test_resource_bad_type(admin_api_client, inv_rd, rando, organization):
    """If giving object_id, type is implied from role definition.

    When giving ansible_id that no longer holds true, and user can give any type.
    This expects a validation error when the object type does not match the role type.
    """
    resource = Resource.objects.get(object_id=organization.pk, content_type=ContentType.objects.get_for_model(organization).pk)
    url = reverse('roleuserassignment-list')
    data = dict(role_definition=inv_rd.id, user=rando.id, resource=str(resource.ansible_id))
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 400, response.data
    assert 'resource' in response.data, response.data
    assert 'organization does not match role type of inventory' in str(response.data['resource'])
