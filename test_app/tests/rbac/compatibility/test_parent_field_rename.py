import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from ansible_base.rbac.models import RoleDefinition
from ansible_base.rbac.permission_registry import permission_registry
from test_app.models import Organization, ParentName

MODEL_PERMS = ['change_parentname', 'view_parentname', 'delete_parentname']


@pytest.fixture
def pn_rd():
    return RoleDefinition.objects.create_from_permissions(
        name='ParentName Admin',
        permissions=MODEL_PERMS,
        content_type=ContentType.objects.get_for_model(ParentName),
    )


@pytest.fixture
def org_pn_rd():
    return RoleDefinition.objects.create_from_permissions(
        name='Organization-wide ParentName Admin',
        permissions=MODEL_PERMS + ['add_parentname', 'view_organization'],
        content_type=ContentType.objects.get_for_model(Organization),
    )


@pytest.fixture
def pn_obj(organization):
    return ParentName.objects.create(my_organization=organization)


def test_parent_name_registry_data():
    assert permission_registry.get_parent_fd_name(ParentName) == 'my_organization'
    assert permission_registry.get_parent_model(ParentName) == Organization
    assert ParentName in set(dict(permission_registry.get_child_models(Organization)).values())


@pytest.mark.django_db
def test_give_user_obj_permission(user, pn_rd, pn_obj, organization):
    pn_obj.my_organization == organization  # sanity, this is the point of testing
    assert not user.has_obj_perm(pn_obj, 'change')
    assert set(ParentName.access_qs(user)) == set()

    pn_rd.give_permission(user, pn_obj)

    assert user.has_obj_perm(pn_obj, 'change')
    assert set(ParentName.access_qs(user)) == set([pn_obj])


@pytest.mark.django_db
def test_give_user_organization_wide_permission(user, org_pn_rd, pn_obj, organization):
    assert not user.has_obj_perm(pn_obj, 'change')
    assert set(ParentName.access_qs(user)) == set()

    org_pn_rd.give_permission(user, organization)

    assert user.has_obj_perm(pn_obj, 'change')
    assert set(ParentName.access_qs(user)) == set([pn_obj])


@pytest.mark.django_db
def test_make_org_api_assignment(admin_api_client, org_pn_rd, organization, pn_obj, user):
    url = reverse('roleuserassignment-list')
    assert not user.has_obj_perm(pn_obj, 'change')
    data = dict(role_definition=org_pn_rd.id, user=user.id, content_type='aap.parentname', object_id=organization.id)
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 201, response.data

    assert user.has_obj_perm(pn_obj, 'change')
    assert set(ParentName.access_qs(user)) == set([pn_obj])
