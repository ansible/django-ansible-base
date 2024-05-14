from uuid import uuid4

import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from ansible_base.rbac.models import ObjectRole, RoleEvaluation
from ansible_base.rbac.triggers import update_after_assignment
from ansible_base.resource_registry.models import Resource


@pytest.mark.django_db
def test_user_assignment_ansible_id(admin_api_client, inv_rd, rando, inventory):
    resource = Resource.objects.get(object_id=rando.pk, content_type=ContentType.objects.get_for_model(rando).pk)
    url = reverse('roleuserassignment-list')
    data = dict(role_definition=inv_rd.id, user_ansible_id=str(resource.ansible_id), object_id=inventory.id)
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 201, response.data
    assert rando.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
def test_user_assinment_resource_deleted(admin_api_client, rando, organization, org_admin_rd):
    resource = Resource.objects.get(object_id=rando.pk, content_type=ContentType.objects.get_for_model(rando).pk)
    url = reverse('roleuserassignment-list')
    data = dict(role_definition=org_admin_rd.id, user_ansible_id=str(resource.ansible_id), object_id=organization.id)

    # sanity assertions of initial state
    assert hasattr(organization, 'resource')
    assert not ObjectRole.objects.filter(object_id=organization.id, content_type=ContentType.objects.get_for_model(organization)).exists()

    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 201, response.data
    assert rando.has_obj_perm(organization, 'change')

    # test duplicate assignment
    organization.resource.delete()
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code in (201, 200), response.data


@pytest.mark.django_db
def test_user_assinment_unmigrated_assignment(admin_api_client, rando, organization, org_admin_rd):
    # Mock an object from from before assignment link was added
    org_ct = ContentType.objects.get_for_model(organization)
    object_role = ObjectRole.objects.create(object_id=organization.pk, content_type=org_ct, role_definition=org_admin_rd)
    update_after_assignment([], [object_role])

    url = reverse('roleuserassignment-list')
    data = dict(role_definition=org_admin_rd.id, user_ansible_id=str(rando.resource.ansible_id), object_id=organization.id)

    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 201, response.data
    assert rando.has_obj_perm(organization, 'change')


@pytest.mark.django_db
def test_team_assignment_ansible_id(admin_api_client, inv_rd, team, inventory, member_rd, rando):
    member_rd.give_permission(rando, team)
    team_ct = ContentType.objects.get_for_model(team)
    resource = Resource.objects.get(object_id=team.pk, content_type=team_ct.pk)
    url = reverse('roleteamassignment-list')
    data = dict(role_definition=inv_rd.id, content_type='aap.inventory', team_ansible_id=str(resource.ansible_id), object_id=inventory.id)
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
    url = reverse('roleuserassignment-list')
    data = dict(role_definition=org_inv_rd.id, user=rando.id, object_ansible_id=str(resource.ansible_id))
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
def test_invalid_ansible_id(admin_api_client, org_inv_rd, rando):
    url = reverse('roleuserassignment-list')
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
    url = reverse('roleuserassignment-list')
    data = dict(role_definition=inv_rd.id, user=rando.id, object_ansible_id=str(resource.ansible_id))
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 400, response.data
    assert 'organization does not match role type of inventory' in str(response.data['object_ansible_id'])
