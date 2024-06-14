import pytest
from django.urls import reverse

from ansible_base.rbac.models import DABPermission, RoleDefinition
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.rbac.validators import validate_permissions_for_model
from test_app.models import PublicData


@pytest.fixture
def public_item(organization):
    return PublicData.objects.create(name='some data', data={'foo': 'bar'}, organization=organization)


def test_unprivledged_user_can_view(public_item, rando):
    assert not rando.has_obj_perm(public_item, 'change')
    # calling has_obj_perm with 'view' is still expected to error
    assert public_item in PublicData.access_qs(rando)


def test_unprivledged_user_can_view_api(public_item, user_api_client):
    url = reverse('publicdata-detail', kwargs={'pk': public_item.pk})
    response = user_api_client.get(url)
    assert response.status_code == 200, response.data
    assert response.data['id'] == public_item.id


@pytest.mark.django_db
def test_role_definition_validator_without_view():
    pd_ct = permission_registry.content_type_model.objects.get_for_model(PublicData)
    permission = DABPermission.objects.get(codename='delete_publicdata')
    validate_permissions_for_model(permissions=[permission], content_type=pd_ct)  # does not raise error


@pytest.mark.django_db
def test_custom_role_for_public_model(admin_api_client, rando, public_item):
    url = reverse('roledefinition-list')
    data = {'name': 'Public data editor', 'permissions': ['local.change_publicdata'], 'content_type': 'local.publicdata'}
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 201, response.data

    rd = RoleDefinition.objects.get(id=response.data['id'])
    assert not rando.has_obj_perm(public_item, 'change')
    rd.give_permission(rando, public_item)
    assert rando.has_obj_perm(public_item, 'change')
