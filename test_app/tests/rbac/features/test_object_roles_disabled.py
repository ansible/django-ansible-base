import pytest
from django.contrib.contenttypes.models import ContentType
from rest_framework.exceptions import ValidationError
from rest_framework.reverse import reverse

from ansible_base.rbac.models import DABPermission, RoleDefinition
from ansible_base.rbac.validators import permissions_allowed_for_role, validate_permissions_for_model
from test_app.models import MemberGuide, User


@pytest.fixture
def member_guide(organization):
    return MemberGuide.objects.create(name='Beginner stuff', article='This is where you file a ticket: https://foo.invalid', organization=organization)


@pytest.mark.django_db
def test_org_admin_access(rando, organization, member_guide):
    assert not rando.has_obj_perm(member_guide, 'change')
    RoleDefinition.objects.managed.org_admin.give_permission(rando, organization)
    assert rando.has_obj_perm(member_guide, 'change')


@pytest.mark.django_db
def test_role_definition_validation_error():
    mg_ct = ContentType.objects.get_for_model(MemberGuide)
    permissions = [DABPermission.objects.get(codename='view_memberguide')]
    with pytest.raises(ValidationError) as exc:
        validate_permissions_for_model(permissions, mg_ct)
    assert 'Creating roles for the member guide model is disabled' in str(exc)


@pytest.mark.django_db
def test_custom_role_denied_elegantly(admin_api_client):
    url = reverse('roledefinition-list')
    data = {'name': 'MemberGuide object role', 'permissions': ['local.view_memberguide'], 'content_type': 'local.memberguide'}
    response = admin_api_client.post(url, data=data, format='json')
    assert response.status_code == 400, response.data
    assert 'Creating roles for the member guide model is disabled' in str(response.data['content_type'])


@pytest.mark.django_db
def test_role_metadata_without_object_roles(user_api_client):
    url = reverse('role-metadata')
    response = user_api_client.get(url)
    assert 'allowed_permissions' in response.data
    allowed_permissions = response.data['allowed_permissions']
    assert 'shared.organization' in allowed_permissions.keys()  # sanity
    assert 'aap.change_memberguide' in allowed_permissions['shared.organization']


@pytest.mark.django_db
def test_custom_role_for_organization(admin_api_client, rando, member_guide, organization):
    url = reverse('roledefinition-list')
    data = {'name': 'MemberGuide view', 'permissions': ['local.view_memberguide'], 'content_type': 'local.organization'}
    response = admin_api_client.post(url, data=data, format='json')
    assert response.status_code == 201, response.data

    assert not rando.has_obj_perm(member_guide, 'view')
    rd = RoleDefinition.objects.get(id=response.data['id'])
    rd.give_permission(rando, organization)
    assert rando.has_obj_perm(member_guide, 'view')


@pytest.fixture
def member_guide_create_rd(organization):
    # Create a new role that allows a user to create member guides
    return RoleDefinition.objects.create_from_permissions(
        name='Member Guide Author Role', content_type=ContentType.objects.get_for_model(organization), permissions=['add_memberguide', 'view_organization']
    )


@pytest.mark.django_db
def test_creator_role_works_with_no_obj_role(member_guide_create_rd, rando, member_guide):
    assert not rando.has_obj_perm(member_guide, 'change')
    assignment = RoleDefinition.objects.give_creator_permissions(rando, member_guide)
    assert assignment.role_definition.managed is True
    assert 'creator' in assignment.role_definition.name
    assert rando.has_obj_perm(member_guide, 'change')


@pytest.mark.django_db
def test_member_guide_add_story(admin_api_client, user_api_client, user, organization, member_guide, member_guide_create_rd):
    # Assign user this permission using the API, should get a creator role
    response = admin_api_client.post(
        reverse('roleuserassignment-list'), data={'role_definition': member_guide_create_rd.id, 'user': user.id, 'object_id': organization.id}, format='json'
    )
    assert response.status_code == 201, response.data

    # Now use this new permission to create a new member guide as the user
    response = user_api_client.post(
        reverse('memberguide-list'), data={'organization': organization.id, 'name': 'Rule 1', 'article': 'No deployments allowed on Fridays'}, format='json'
    )
    assert response.status_code == 201, response.data
    member_guide = MemberGuide.objects.get(id=response.data['id'])

    # user has permission to object they created
    assert user.has_obj_perm(member_guide, 'change')
    creator_rd = RoleDefinition.objects.get(name__icontains='-creator')
    assert creator_rd.content_type.model_class() is MemberGuide  # sanity

    # Other users now can not be assigned the creator role
    bob = User.objects.create(username='bob')
    response = admin_api_client.post(
        reverse('roleuserassignment-list'), data={'role_definition': creator_rd.id, 'user': bob.id, 'object_id': member_guide.id}, format='json'
    )
    assert response.status_code == 400, response.data
    assert 'Roles are not assignable through the API for this model' in str(response.data)
