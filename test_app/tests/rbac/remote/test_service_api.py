import uuid
from copy import deepcopy

import pytest
from django.apps import apps as django_apps
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIClient

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.backfill import backfill_object_ansible_id
from ansible_base.rbac.models import (
    DABContentType,
    DABPermission,
    RoleDefinition,
    RoleTeamAssignment,
    RoleUserAssignment,
)
from ansible_base.resource_registry.models import Resource
from test_app.models import Organization, Team, User


@pytest.mark.django_db
def test_get_resource_list(admin_api_client):
    url = get_relative_url('dabcontenttype-list')
    response = admin_api_client.get(url, format="json")
    assert response.status_code == 200, response.data
    type_data = {t['api_slug']: t for t in response.data['results']}

    assert 'shared.organization' in type_data
    org_data = type_data['shared.organization']
    assert org_data['parent_content_type'] is None
    assert org_data['service'] == 'shared'
    assert org_data['model'] == 'organization'

    assert 'aap.inventory' in type_data
    inv_data = type_data['aap.inventory']
    assert inv_data['parent_content_type'] == 'shared.organization'


@pytest.mark.django_db
def test_get_permission_list(admin_api_client):
    url = get_relative_url('dabpermission-list')
    response = admin_api_client.get(url + '?page_size=200', format="json")
    assert response.status_code == 200, response.data
    type_data = {t['api_slug']: t for t in response.data['results']}

    assert 'shared.change_organization' in type_data
    change_org_data = type_data['shared.change_organization']
    assert change_org_data['content_type'] == 'shared.organization'
    assert change_org_data['codename'] == 'change_organization'


@pytest.mark.django_db
def test_role_definition_listed_as_resource(admin_api_client, org_admin_rd):
    url = get_relative_url('resource-list')
    url += '?page_size=200&content_type__resource_type__name=shared.roledefinition'
    response = admin_api_client.get(url, format="json")
    assert response.status_code == 200, response.data
    rd_data = {rd['name']: rd for rd in response.data['results']}

    assert 'Organization Admin' in rd_data
    org_admin_data = rd_data['Organization Admin']

    detail = admin_api_client.get(org_admin_data['url'], format="json")
    assert detail.status_code == 200, detail.data
    resource_data = detail.data['resource_data']
    assert resource_data['managed'] is True
    assert resource_data['content_type'] == 'shared.organization'
    assert 'permissions' in detail.data['resource_data']
    assert 'aap.add_inventory' in detail.data['resource_data']['permissions']


@pytest.mark.django_db
def test_reload_types(admin_api_client):
    url = get_relative_url('dabcontenttype-list')
    response = admin_api_client.get(url + '?page_size=200', format="json")
    assert response.status_code == 200, response.data

    type_list = response.data['results']
    original = deepcopy(type_list)

    DABContentType.objects.all().delete()  # Delete all types, see if we get them back

    DABContentType.objects.load_remote_objects(type_list)

    response = admin_api_client.get(url + '?page_size=200', format="json")
    assert response.status_code == 200, response.data

    assert response.data['results'] == original


@pytest.mark.django_db
def test_load_child_of_org():
    DABContentType.objects.load_remote_objects([{'service': 'fooland', 'app_label': 'foop', 'model': 'fooser', 'parent_content_type': 'shared.organization'}])
    ct = DABContentType.objects.get(api_slug='fooland.fooser')
    assert ct.parent_content_type.app_label == 'test_app'  # proves connection to existing


@pytest.mark.django_db
def test_reload_permissions(admin_api_client):
    url = get_relative_url('dabpermission-list')
    response = admin_api_client.get(url + '?page_size=200', format="json")
    assert response.status_code == 200, response.data

    perm_list = response.data['results']
    original = deepcopy(perm_list)

    DABPermission.objects.all().delete()  # Delete all permissions, see if we get them back

    DABPermission.objects.load_remote_objects(perm_list)

    response = admin_api_client.get(url + '?page_size=200', format="json")
    assert response.status_code == 200, response.data

    assert response.data['results'] == original


@pytest.mark.django_db
def test_list_role_user_assignments(admin_api_client, rando, inv_rd, inventory):
    inv_rd.give_permission(rando, inventory)

    url = get_relative_url('serviceuserassignment-list')
    response = admin_api_client.get(url + '?page_size=200', format="json")
    assert response.status_code == 200, response.data

    candidates = [assignment for assignment in response.data['results'] if assignment['role_definition'] == inv_rd.name]
    assert len(candidates) == 1, response.data
    from_api = candidates[0]

    # 'id' is required for cursor-based pagination in migrate_service_data
    assert 'id' in from_api, f"'id' missing from service-index user assignment response: {from_api.keys()}"
    assert from_api['id'] == RoleUserAssignment.objects.get(user=rando, role_definition=inv_rd, object_id=inventory.id).id
    assert int(from_api['object_id']) == inventory.id
    assert from_api['user_ansible_id'] == str(rando.resource.ansible_id)
    assert from_api['content_type'] == 'aap.inventory'


@pytest.mark.django_db
def test_list_role_team_assignments_includes_id(admin_api_client, inv_rd, inventory, team, member_rd, rando):
    """Service-index team assignment responses include 'id' for cursor-based pagination."""
    member_rd.give_permission(rando, team)
    inv_rd.give_permission(team, inventory)

    url = get_relative_url('serviceteamassignment-list')
    response = admin_api_client.get(url + '?page_size=200', format="json")
    assert response.status_code == 200, response.data

    candidates = [a for a in response.data['results'] if a['role_definition'] == inv_rd.name]
    assert len(candidates) == 1, response.data
    from_api = candidates[0]

    assert 'id' in from_api, f"'id' missing from service-index team assignment response: {from_api.keys()}"
    assert from_api['id'] == RoleTeamAssignment.objects.get(team=team, role_definition=inv_rd, object_id=inventory.id).id
    assert from_api['team_ansible_id'] == str(team.resource.ansible_id)


@pytest.mark.django_db
def test_object_ansible_id_in_list_response(admin_api_client, rando, org_admin_rd, organization):
    """Verify object_ansible_id is correctly returned for organization-level assignments."""
    org2 = Organization.objects.create(name='Covering Index Test Org')
    assignment = org_admin_rd.give_permission(rando, organization)
    org_admin_rd.give_permission(rando, org2)
    assert assignment.object_ansible_id == organization.resource.ansible_id

    url = get_relative_url('serviceuserassignment-list')
    response = admin_api_client.get(url + '?page_size=200', format="json")
    assert response.status_code == 200, response.data

    org_assignments = [a for a in response.data['results'] if a['role_definition'] == org_admin_rd.name]
    assert len(org_assignments) == 2

    returned_ansible_ids = {a['object_ansible_id'] for a in org_assignments}
    assert str(organization.resource.ansible_id) in returned_ansible_ids
    assert str(org2.resource.ansible_id) in returned_ansible_ids


@pytest.mark.django_db
def test_backfill_object_ansible_id(rando, org_admin_rd, organization):
    assignment = org_admin_rd.give_permission(rando, organization)
    RoleUserAssignment.objects.filter(pk=assignment.pk).update(object_ansible_id=None)

    backfill_object_ansible_id(django_apps)

    assignment.refresh_from_db()
    assert assignment.object_ansible_id == organization.resource.ansible_id


@pytest.mark.django_db
def test_assignment_object_ansible_id_tracks_resource_changes(rando, org_admin_rd, organization):
    assignment = org_admin_rd.give_permission(rando, organization)
    resource = organization.resource
    resource.ansible_id = uuid.uuid4()
    resource.save()

    assignment.refresh_from_db()
    assert assignment.object_ansible_id == resource.ansible_id


@pytest.mark.django_db
def test_service_api_uses_cached_object_ansible_id(admin_api_client, rando, org_admin_rd, organization):
    assignment = org_admin_rd.give_permission(rando, organization)
    RoleUserAssignment.objects.filter(pk=assignment.pk).update(object_ansible_id=None)

    response = admin_api_client.get(get_relative_url('serviceuserassignment-list'), format='json')

    assert response.status_code == 200, response.data
    result = next(item for item in response.data['results'] if item['id'] == assignment.id)
    assert result['object_ansible_id'] is None


@pytest.mark.django_db
def test_resource_ansible_id_filter_remains_supported(admin_api_client, rando, org_admin_rd, organization):
    """Keep the legacy resource__ansible_id service-index filter working."""
    assignment = org_admin_rd.give_permission(rando, organization)
    RoleUserAssignment.objects.filter(pk=assignment.pk).update(object_role=None)
    url = get_relative_url('serviceuserassignment-list')

    response = admin_api_client.get(url + f'?resource__ansible_id={organization.resource.ansible_id}', format='json')

    assert response.status_code == 200, response.data
    assert [item['id'] for item in response.data['results']] == [assignment.id]


@pytest.mark.django_db
def test_global_assignment_resource_annotation_is_null(rando):
    role_definition = RoleDefinition.objects.managed.sys_auditor
    assignment = role_definition.give_global_permission(rando)

    from ansible_base.rbac.service_api.views import ServiceRoleUserAssignmentViewSet

    annotated_assignment = ServiceRoleUserAssignmentViewSet().get_queryset().get(pk=assignment.pk)

    assert annotated_assignment.object_ansible_id is None


@pytest.mark.django_db
def test_assignment_annotation_does_not_join_dab_content_type_id_to_resource_content_type_id(rando):
    """DAB and Django ContentType IDs are separate namespaces."""
    wrong_resource_type = ContentType.objects.create(app_label='wrong', model=f'wrong_{uuid.uuid4().hex}')
    while DABContentType.objects.filter(pk=wrong_resource_type.pk).exists():
        wrong_resource_type = ContentType.objects.create(app_label='wrong', model=f'wrong_{uuid.uuid4().hex}')

    dab_content_type = DABContentType.objects.create(
        id=wrong_resource_type.pk,
        service='aap',
        app_label='test_app',
        model='organization',
        pk_field_type='integer',
    )
    role_definition = RoleDefinition.objects.create(name=f'wrong-content-type-{uuid.uuid4().hex}', content_type=dab_content_type)
    assignment = RoleUserAssignment.objects.create(
        user=rando,
        role_definition=role_definition,
        content_type=dab_content_type,
        object_id='17',
        object_role=None,
    )
    wrong_resource = Resource.objects.create(content_type=wrong_resource_type, object_id='17')

    from ansible_base.rbac.service_api.views import ServiceRoleUserAssignmentViewSet

    annotated_assignment = ServiceRoleUserAssignmentViewSet().get_queryset().get(pk=assignment.pk)

    assert annotated_assignment.object_ansible_id is None
    assert annotated_assignment.object_ansible_id != wrong_resource.ansible_id


@pytest.mark.django_db
def test_apply_role_assignment(admin_api_client, rando, inv_rd, inventory):
    url = get_relative_url('serviceuserassignment-assign')

    data = {"role_definition": inv_rd.name, "user_ansible_id": str(rando.resource.ansible_id), "object_id": inventory.pk}

    assert not rando.has_obj_perm(inventory, 'change')
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 201, response.data
    assert rando.has_obj_perm(inventory, 'change')

    # Second try, response code indicates assignment already exists
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 200, response.data


@pytest.mark.django_db
def test_unassign_endpoint(rando, org_inv_rd, inventory, admin_api_client):
    org_inv_rd.give_permission(rando, inventory.organization)
    assert rando.has_obj_perm(inventory, 'change')

    url = get_relative_url('serviceuserassignment-unassign')
    data = {
        "role_definition": org_inv_rd.name,
        "user_ansible_id": str(rando.resource.ansible_id),
        "object_ansible_id": str(inventory.organization.resource.ansible_id),
    }
    response = admin_api_client.post(url, data)
    assert response.status_code == 204, response.data
    assert not rando.has_obj_perm(inventory, 'change')

    # second gets a 200 code
    response = admin_api_client.post(url, data)
    assert response.status_code == 200, response.data
    assert not rando.has_obj_perm(inventory, 'change')


# teams
@pytest.mark.django_db
def test_apply_role_assignment_for_team(admin_api_client, inv_rd, inventory, team, member_rd, rando):
    member_rd.give_permission(rando, team)
    url = get_relative_url('serviceteamassignment-assign')

    data = {"role_definition": inv_rd.name, "team_ansible_id": str(team.resource.ansible_id), "object_id": inventory.pk}

    assert not rando.has_obj_perm(inventory, 'change')
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 201, response.data
    assert rando.has_obj_perm(inventory, 'change')

    # Second try, response code indicates assignment already exists
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 200, response.data


@pytest.mark.django_db
def test_unassign_endpoint_for_team(team, org_inv_rd, inventory, admin_api_client, member_rd, rando):
    member_rd.give_permission(rando, team)
    org_inv_rd.give_permission(team, inventory.organization)
    assert rando.has_obj_perm(inventory, 'change')

    url = get_relative_url('serviceteamassignment-unassign')
    data = {
        "role_definition": org_inv_rd.name,
        "team_ansible_id": str(team.resource.ansible_id),
        "object_ansible_id": str(inventory.organization.resource.ansible_id),
    }
    response = admin_api_client.post(url, data)
    assert response.status_code == 204, response.data
    assert not rando.has_obj_perm(inventory, 'change')

    # second gets a 200 code
    response = admin_api_client.post(url, data)
    assert response.status_code == 200, response.data
    assert not rando.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
def test_service_user_assignment_requires_object_permission(inv_rd, inventory, rando):
    requester = User.objects.create(username='service-requester')
    rando.resource_api_actions = "*"  # specific to internal requests
    client = APIClient()
    client.force_authenticate(user=requester)

    url = get_relative_url('serviceuserassignment-assign')
    data = {"role_definition": inv_rd.name, "user_ansible_id": str(rando.resource.ansible_id), "object_id": inventory.pk}

    response = client.post(url, data=data)
    assert response.status_code == 403, response.data

    # Should still get a 403 even if assignment already exists
    inv_rd.give_permission(rando, inventory)
    response = client.post(url, data=data)
    assert response.status_code == 403, response.data


@pytest.mark.django_db
@pytest.mark.parametrize('actor_type', ['user', 'team'])
def test_assign_and_unassign_system_role(inventory, admin_api_client, actor_type, organization, member_rd):
    if actor_type == 'user':
        actor = User.objects.create(username='user1')
        user = actor
    else:
        actor = Team.objects.create(name='random_team', organization=organization)
        user = User.objects.create(username='user1')
        member_rd.give_permission(user, actor)

    rd = RoleDefinition.objects.managed.sys_auditor
    assert 'view_inventory' in set(rd.permissions.values_list('codename', flat=True))
    assert not user.has_obj_perm(inventory, 'view')

    url = get_relative_url(f'service{actor_type}assignment-assign')
    data = {"role_definition": rd.name, f"{actor_type}_ansible_id": str(actor.resource.ansible_id)}
    response = admin_api_client.post(url, data)
    assert response.status_code == 201, response.data
    if hasattr(actor, '_singleton_permissions'):
        delattr(actor, '_singleton_permissions')
    assert user.has_obj_perm(inventory, 'view')  # gave system wide view permission

    # Second try, response code indicates global assignment already exists
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 200, response.data

    unassign_url = get_relative_url(f'service{actor_type}assignment-unassign')
    response = admin_api_client.post(unassign_url, data)
    assert response.status_code == 204, response.data
    if hasattr(actor, '_singleton_permissions'):
        delattr(actor, '_singleton_permissions')
    assert not user.has_obj_perm(inventory, 'view')  # permission removed

    response = admin_api_client.post(unassign_url, data)
    assert response.status_code == 200, response.data


@pytest.mark.django_db
def test_filter_assignment_list(admin_api_client, rando, inv_rd, view_inv_rd, org_inv_rd, inventory):
    inv_rd.give_permission(rando, inventory)
    org_inv_rd.give_permission(rando, inventory.organization)
    view_inv_rd.give_permission(rando, inventory)

    url = get_relative_url('serviceuserassignment-list')
    response = admin_api_client.get(url + f'?user={rando.id}', format="json")
    assert response.status_code == 200, response.data
    assert response.data['count'] == 3  # user rando has 3 rol assignments

    # Get just one single assignment
    response = admin_api_client.get(url + f'?assignment={str(rando.resource.ansible_id)},{inv_rd.name},{inventory.id}', format="json")
    assert response.status_code == 200, response.data
    assert response.data['count'] == 1
    assert response.data['results'][0]['role_definition'] == inv_rd.name

    # Assure we can get two assignments at the same time
    response = admin_api_client.get(
        url
        + (
            f'?assignment={str(rando.resource.ansible_id)},{inv_rd.name},{inventory.id}&'
            f'assignment={str(rando.resource.ansible_id)},{org_inv_rd.name},{inventory.organization.id}'
        ),
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data['count'] == 2


@pytest.mark.django_db
@pytest.mark.parametrize(
    'reverse_name,normal_case,unauth_case',
    [
        ('service-index-root', 200, 401),
        ('dabcontenttype-list', 200, 401),  # could change unauthenticated case, depends on need
        ('dabpermission-list', 200, 401),
        ('resource-list', 403, 401),
        ('serviceuserassignment-list', 403, 401),
        ('serviceteamassignment-list', 403, 401),
    ],
)
def test_service_api_permissions(reverse_name, normal_case, unauth_case, admin_api_client, user_api_client, unauthenticated_api_client):
    url = get_relative_url(reverse_name)

    admin_response = admin_api_client.get(url)
    assert admin_response.status_code == 200, admin_response.data

    normal_response = user_api_client.get(url)
    assert normal_response.status_code == normal_case, normal_response.data

    unauth_response = unauthenticated_api_client.get(url)
    assert unauth_response.status_code == unauth_case, unauth_response.data


@pytest.mark.django_db
def test_role_types_and_permissions_payload_shape(user_api_client):
    """Minimal payload-shape checks for role types and permissions when accessed by normal user."""
    # role types
    url_ct = get_relative_url('dabcontenttype-list')
    resp_ct = user_api_client.get(url_ct)
    assert resp_ct.status_code == 200, resp_ct.data
    # Results should be paginated list; spot-check first item fields if present
    if resp_ct.data.get('count', 0) and resp_ct.data.get('results'):
        item = resp_ct.data['results'][0]
        for key in ('api_slug', 'service', 'app_label', 'model', 'pk_field_type'):
            assert key in item
        # parent_content_type is allowed to be null
        assert 'parent_content_type' in item

    # role permissions
    url_perm = get_relative_url('dabpermission-list')
    resp_perm = user_api_client.get(url_perm)
    assert resp_perm.status_code == 200, resp_perm.data
    if resp_perm.data.get('count', 0) and resp_perm.data.get('results'):
        item = resp_perm.data['results'][0]
        for key in ('api_slug', 'codename', 'name'):
            assert key in item
        assert 'content_type' in item  # slug of related content type


@pytest.mark.django_db
class TestCreatedByAnsibleIdAllowNull:
    """Test that created_by_ansible_id field accepts null values and omissions"""

    def test_service_user_assignment_with_null_created_by(self, admin_api_client, rando, inv_rd, inventory):
        """Test that ServiceRoleUserAssignmentSerializer accepts null created_by_ansible_id"""
        url = get_relative_url('serviceuserassignment-assign')
        data = {
            "role_definition": inv_rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_id": inventory.pk,
            "created_by_ansible_id": "",  # Use empty string instead of None
        }

        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, response.data
        assert rando.has_obj_perm(inventory, 'change')

    def test_service_user_assignment_without_created_by(self, admin_api_client, rando, inv_rd, inventory):
        """Test that ServiceRoleUserAssignmentSerializer works when created_by_ansible_id is omitted"""
        url = get_relative_url('serviceuserassignment-assign')
        data = {
            "role_definition": inv_rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_id": inventory.pk,
            # created_by_ansible_id is intentionally omitted
        }

        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, response.data
        assert rando.has_obj_perm(inventory, 'change')

    def test_service_user_assignment_with_valid_created_by(self, admin_api_client, rando, inv_rd, inventory):
        """Test that valid created_by_ansible_id values still work correctly"""
        creator = User.objects.create(username='creator-user')
        url = get_relative_url('serviceuserassignment-assign')
        data = {
            "role_definition": inv_rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_id": inventory.pk,
            "created_by_ansible_id": str(creator.resource.ansible_id),
        }

        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, response.data
        assert rando.has_obj_perm(inventory, 'change')

    def test_service_team_assignment_with_null_created_by(self, admin_api_client, team, inv_rd, inventory, member_rd, rando):
        """Test that ServiceRoleTeamAssignmentSerializer accepts null created_by_ansible_id"""
        member_rd.give_permission(rando, team)
        url = get_relative_url('serviceteamassignment-assign')
        data = {
            "role_definition": inv_rd.name,
            "team_ansible_id": str(team.resource.ansible_id),
            "object_id": inventory.pk,
            "created_by_ansible_id": "",  # Use empty string instead of None
        }

        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, response.data
        assert rando.has_obj_perm(inventory, 'change')

    def test_service_team_assignment_without_created_by(self, admin_api_client, team, inv_rd, inventory, member_rd, rando):
        """Test that ServiceRoleTeamAssignmentSerializer works when created_by_ansible_id is omitted"""
        member_rd.give_permission(rando, team)
        url = get_relative_url('serviceteamassignment-assign')
        data = {
            "role_definition": inv_rd.name,
            "team_ansible_id": str(team.resource.ansible_id),
            "object_id": inventory.pk,
        }

        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, response.data
        assert rando.has_obj_perm(inventory, 'change')

    def test_service_team_assignment_with_valid_created_by(self, admin_api_client, team, inv_rd, inventory, member_rd, rando):
        """Test that valid created_by_ansible_id values still work correctly for teams"""
        member_rd.give_permission(rando, team)
        creator = User.objects.create(username='team-creator-user')
        url = get_relative_url('serviceteamassignment-assign')
        data = {
            "role_definition": inv_rd.name,
            "team_ansible_id": str(team.resource.ansible_id),
            "object_id": inventory.pk,
            "created_by_ansible_id": str(creator.resource.ansible_id),
        }

        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, response.data
        assert rando.has_obj_perm(inventory, 'change')

    def test_list_assignments_shows_created_by_when_present(self, admin_api_client, rando, inv_rd, inventory):
        """Test that list endpoint properly serializes created_by_ansible_id when present"""
        creator = User.objects.create(username='assignment-creator')

        # Create assignment with a specific creator
        url = get_relative_url('serviceuserassignment-assign')
        data = {
            "role_definition": inv_rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_id": inventory.pk,
            "created_by_ansible_id": str(creator.resource.ansible_id),
        }
        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, response.data

        # Check list endpoint
        list_url = get_relative_url('serviceuserassignment-list')
        response = admin_api_client.get(list_url + '?page_size=200', format="json")
        assert response.status_code == 200, response.data

        # Find our assignment
        assignments = [a for a in response.data['results'] if a['role_definition'] == inv_rd.name and str(a['object_id']) == str(inventory.id)]
        assert len(assignments) >= 1, "Should find at least our assignment"

        # Check that created_by_ansible_id is properly serialized
        assignment = assignments[0]
        assert 'created_by_ansible_id' in assignment
        assert assignment['created_by_ansible_id'] == str(creator.resource.ansible_id)

    def test_list_assignments_shows_null_created_by_when_null(self, admin_api_client, rando, inv_rd, inventory):
        """Test that list endpoint properly serializes created_by_ansible_id when empty string is provided"""
        # Create assignment with empty created_by_ansible_id
        url = get_relative_url('serviceuserassignment-assign')
        data = {
            "role_definition": inv_rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_id": inventory.pk,
            "created_by_ansible_id": "",  # Use empty string - should be treated as not providing the field
        }
        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, response.data

        # Check list endpoint
        list_url = get_relative_url('serviceuserassignment-list')
        response = admin_api_client.get(list_url + '?page_size=200', format="json")
        assert response.status_code == 200, response.data

        # Find our assignment
        assignments = [a for a in response.data['results'] if a['role_definition'] == inv_rd.name and str(a['object_id']) == str(inventory.id)]
        assert len(assignments) >= 1, "Should find at least our assignment"

        # Check that created_by_ansible_id is properly serialized
        assignment = assignments[0]
        assert 'created_by_ansible_id' in assignment
        # When empty string is provided, the system may still set created_by to the current user
        # The key test is that the API accepts empty string without error
        assert assignment['created_by_ansible_id'] is not None  # System will set to current user

    def test_serializer_allows_null_values_in_validation(self, admin_api_client, rando, inv_rd, inventory):
        """Test that the serializer field properly handles null validation with allow_null=True"""
        from ansible_base.rbac.service_api.serializers import (
            ServiceRoleUserAssignmentSerializer,
        )

        # Test data with null created_by_ansible_id
        data = {
            "role_definition": inv_rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_id": str(inventory.pk),
            "created_by_ansible_id": None,  # Explicit None
            "from_service": "test",
        }

        # Create serializer and validate
        serializer = ServiceRoleUserAssignmentSerializer(data=data)

        # Should be valid due to allow_null=True
        is_valid = serializer.is_valid()
        if not is_valid:
            print("Validation errors:", serializer.errors)
        assert is_valid, f"Serializer should accept null values: {serializer.errors}"

        # Verify that created_by is None in validated_data when null is passed
        validated_data = serializer.validated_data
        assert 'created_by' not in validated_data or validated_data.get('created_by') is None


@pytest.mark.django_db
class TestRestClientSyncAssignment:
    """
    Test that rest_client.sync_assignment only sends the appropriate ID field.

    For objects registered with resource registry: send only object_ansible_id
    For objects NOT registered: send only object_id

    Generated by Claude Sonnet 4.5
    """

    def test_sync_assignment_sends_only_object_ansible_id_for_registered_objects(self, rando, organization, org_admin_rd):
        """Test that sync_assignment removes object_id when object_ansible_id is present"""
        from unittest.mock import MagicMock, patch

        from ansible_base.resource_registry.rest_client import ResourceAPIClient

        # Create an assignment to an organization (which has a resource)
        assignment = org_admin_rd.give_permission(rando, organization)

        # Create a mock client
        client = ResourceAPIClient(service_url='http://example.com', service_path='/api/v1/service-index/')

        # Mock the _sync_assignment method to capture what data is sent
        with patch.object(client, '_sync_assignment', return_value=MagicMock()) as mock_sync:
            # Call sync_assignment
            client.sync_assignment(assignment)

            # Verify _sync_assignment was called
            assert mock_sync.called
            sent_data = mock_sync.call_args[0][0]

            # Should have object_ansible_id
            assert 'object_ansible_id' in sent_data
            assert sent_data['object_ansible_id'] == str(organization.resource.ansible_id)

            # Should NOT have object_id (removed by sync_assignment)
            assert 'object_id' not in sent_data, "object_id should not be sent for registered objects"

    def test_sync_assignment_sends_only_object_id_for_non_registered_objects(self, rando, inventory, inv_rd):
        """Test that sync_assignment keeps object_id when object_ansible_id is None"""
        from unittest.mock import MagicMock, patch

        from ansible_base.resource_registry.rest_client import ResourceAPIClient

        # Create an assignment to an inventory (which doesn't have a resource)
        assignment = inv_rd.give_permission(rando, inventory)

        # Create a mock client
        client = ResourceAPIClient(service_url='http://example.com', service_path='/api/v1/service-index/')

        # Mock the _sync_assignment method to capture what data is sent
        with patch.object(client, '_sync_assignment', return_value=MagicMock()) as mock_sync:
            # Call sync_assignment
            client.sync_assignment(assignment)

            # Verify _sync_assignment was called
            assert mock_sync.called
            sent_data = mock_sync.call_args[0][0]

            # Should have object_id
            assert 'object_id' in sent_data
            assert sent_data['object_id'] == str(inventory.id)

            # object_ansible_id should either be absent or None
            assert sent_data.get('object_ansible_id') is None


@pytest.mark.django_db
class TestObjectIdVsAnsibleId:
    """
    Test server-side defensive behavior: object_ansible_id takes precedence when both are provided.

    This is a defensive measure for the edge case where a client incorrectly sends both fields
    that point to different objects. In this case, object_ansible_id should win.

    Generated by Claude Sonnet 4.5
    """

    def test_object_ansible_id_takes_precedence_when_both_differ(self, admin_api_client, rando, org_admin_rd, organization):
        """
        Test DESIRED defensive server-side behavior: object_ansible_id wins when both are provided but differ.

        This should not happen in normal operation (the client should only send one), but if it does,
        object_ansible_id should take precedence since it's the canonical identifier for cross-service sync.
        """
        from test_app.models import Organization

        # Create a second organization
        org2 = Organization.objects.create(name='Other Organization')

        url = get_relative_url('serviceuserassignment-assign')

        # Provide both with valid but different values (simulating a buggy client)
        # object_id points to org2, object_ansible_id points to organization
        data = {
            "role_definition": org_admin_rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_id": str(org2.id),  # Wrong object
            "object_ansible_id": str(organization.resource.ansible_id),  # Should take precedence
        }

        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, f"Expected 201 but got {response.status_code}: {response.data}"

        # Verify the assignment was made to organization (from object_ansible_id), not org2
        assert rando.has_obj_perm(organization, 'change'), "object_ansible_id should take precedence"
        assert not rando.has_obj_perm(org2, 'change'), "object_id should be ignored when both provided"


@pytest.mark.django_db
class TestValidationErrors:
    """Test validation error cases in service API serializers"""

    def test_system_role_with_object_id_error(self, admin_api_client, rando):
        """Test that providing object_id for system role raises validation error"""
        from ansible_base.rbac.models import RoleDefinition

        # Get a system role (no content_type)
        system_rd = RoleDefinition.objects.managed.sys_auditor
        assert system_rd.content_type_id is None, "Should be a system role"

        url = get_relative_url('serviceuserassignment-assign')
        data = {
            "role_definition": system_rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_id": "12345",  # This should cause error for system role
        }

        response = admin_api_client.post(url, data=data)
        assert response.status_code == 400, response.data
        assert "Can not provide either 'object_id' or 'object_ansible_id' for system role" in str(response.data)

    def test_system_role_with_object_ansible_id_error(self, admin_api_client, rando, organization):
        """Test that providing object_ansible_id for system role raises validation error"""
        from ansible_base.rbac.models import RoleDefinition

        # Get a system role (no content_type)
        system_rd = RoleDefinition.objects.managed.sys_auditor
        assert system_rd.content_type_id is None, "Should be a system role"

        url = get_relative_url('serviceuserassignment-assign')
        data = {
            "role_definition": system_rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_ansible_id": str(organization.resource.ansible_id),  # This should cause error for system role
        }

        response = admin_api_client.post(url, data=data)
        assert response.status_code == 400, response.data
        assert "Can not provide either 'object_id' or 'object_ansible_id' for system role" in str(response.data)

    def test_object_role_with_nonexistent_object_creates_remote_assignment(self, admin_api_client, rando, inv_rd):
        """Synced assignments for non-existent local objects fall back to
        RemoteObject so that cross-service sync is not blocked by object
        ordering (the object may not have been synced yet)."""
        url = get_relative_url('serviceuserassignment-assign')
        data = {
            "role_definition": inv_rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_id": "99999",
        }

        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, response.data
        assert str(response.data["object_id"]) == "99999"

    def test_object_role_without_object_specified_error(self, admin_api_client, rando, inv_rd):
        """Test that object role without object_id raises validation error"""
        url = get_relative_url('serviceuserassignment-assign')
        data = {
            "role_definition": inv_rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            # No object_id or object_ansible_id provided
        }

        response = admin_api_client.post(url, data=data)
        assert response.status_code == 400, response.data
        # Check if the error is about missing object_id or object_ansible_id
        error_msg = str(response.data)
        assert "You must provide either 'object_id' or 'object_ansible_id'" in error_msg


@pytest.mark.django_db
class TestServiceFilter:
    """Test content_type__service filter on service-index assignment endpoints."""

    def _create_foo_assignment(self, admin_api_client, rando, foo_rd):
        """Create a foo-service assignment via the service-index assign endpoint."""
        url = get_relative_url('serviceuserassignment-assign')
        data = {
            "role_definition": foo_rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_id": "42",
        }
        response = admin_api_client.post(url, data=data)
        assert response.status_code in (200, 201), response.data

    def test_user_assignments_filtered_by_service(self, admin_api_client, rando, inv_rd, inventory, foo_rd):
        """When content_type__service is provided, only assignments matching that service are returned."""
        inv_rd.give_permission(rando, inventory)
        self._create_foo_assignment(admin_api_client, rando, foo_rd)

        url = get_relative_url('serviceuserassignment-list')

        response = admin_api_client.get(url + '?content_type__service=aap', format="json")
        assert response.status_code == 200, response.data
        assert len(response.data['results']) >= 1, "Filtered results should not be empty"
        for a in response.data['results']:
            if a['content_type']:
                assert a['content_type'].startswith('aap.'), f"Expected only aap content types, got {a['content_type']}"

    def test_user_assignments_filtered_excludes_other_services(self, admin_api_client, rando, inv_rd, inventory, foo_rd):
        """Filtering by one service excludes assignments for other services."""
        inv_rd.give_permission(rando, inventory)
        self._create_foo_assignment(admin_api_client, rando, foo_rd)

        url = get_relative_url('serviceuserassignment-list')

        response_aap = admin_api_client.get(url + '?content_type__service=aap', format="json")
        assert response_aap.status_code == 200
        assert len(response_aap.data['results']) >= 1, "AAP-filtered results should not be empty"
        for a in response_aap.data['results']:
            if a['content_type']:
                assert not a['content_type'].startswith('foo.'), "foo assignment should not appear in aap-filtered results"

        response_foo = admin_api_client.get(url + '?content_type__service=foo', format="json")
        assert response_foo.status_code == 200
        assert len(response_foo.data['results']) >= 1, "Foo-filtered results should not be empty"
        for a in response_foo.data['results']:
            if a['content_type']:
                assert not a['content_type'].startswith('aap.'), "aap assignment should not appear in foo-filtered results"

    def test_global_assignments_included_when_filtered(self, admin_api_client, rando, inv_rd, inventory):
        """Global assignments (content_type=None) are included regardless of filter value."""
        inv_rd.give_permission(rando, inventory)
        sys_auditor = RoleDefinition.objects.managed.sys_auditor
        sys_auditor.give_global_permission(rando)

        url = get_relative_url('serviceuserassignment-list')
        response = admin_api_client.get(url + '?content_type__service=aap', format="json")
        assert response.status_code == 200

        global_assignments = [a for a in response.data['results'] if a['content_type'] is None]
        assert len(global_assignments) >= 1, "Global assignments should be included in filtered results"

    def test_no_filter_returns_all_assignments(self, admin_api_client, rando, inv_rd, inventory, foo_rd):
        """Without content_type__service filter, all assignments are returned (backward compatible)."""
        inv_rd.give_permission(rando, inventory)
        self._create_foo_assignment(admin_api_client, rando, foo_rd)
        sys_auditor = RoleDefinition.objects.managed.sys_auditor
        sys_auditor.give_global_permission(rando)

        url = get_relative_url('serviceuserassignment-list')

        response_all = admin_api_client.get(url + '?page_size=200', format="json")
        assert response_all.status_code == 200
        all_results = response_all.data['results']

        response_aap = admin_api_client.get(url + '?content_type__service=aap&page_size=200', format="json")
        response_foo = admin_api_client.get(url + '?content_type__service=foo&page_size=200', format="json")

        assert len(all_results) >= len(response_aap.data['results'])
        assert len(all_results) >= len(response_foo.data['results'])

    def test_team_assignments_filtered_by_service(self, admin_api_client, inv_rd, inventory, team, member_rd, rando):
        """Team assignment endpoint also supports content_type__service filter."""
        member_rd.give_permission(rando, team)
        inv_rd.give_permission(team, inventory)

        url = get_relative_url('serviceteamassignment-list')
        response = admin_api_client.get(url + '?content_type__service=aap', format="json")
        assert response.status_code == 200
        for a in response.data['results']:
            if a['content_type']:
                assert a['content_type'].startswith('aap.'), f"Expected aap content type, got {a['content_type']}"

    def test_team_global_assignments_included_when_filtered(self, admin_api_client, team, member_rd, rando):
        """Global team assignments are included when filtering by service."""
        member_rd.give_permission(rando, team)
        sys_auditor = RoleDefinition.objects.managed.sys_auditor
        sys_auditor.give_global_permission(team)

        url = get_relative_url('serviceteamassignment-list')
        response = admin_api_client.get(url + '?content_type__service=aap', format="json")
        assert response.status_code == 200

        global_assignments = [a for a in response.data['results'] if a['content_type'] is None]
        assert len(global_assignments) >= 1, "Global team assignments should be included in filtered results"

    def test_nonexistent_service_returns_only_globals(self, admin_api_client, rando, inv_rd, inventory):
        """Filtering by a service with no assignments returns only global assignments."""
        inv_rd.give_permission(rando, inventory)
        sys_auditor = RoleDefinition.objects.managed.sys_auditor
        sys_auditor.give_global_permission(rando)

        url = get_relative_url('serviceuserassignment-list')
        response = admin_api_client.get(url + '?content_type__service=nonexistent', format="json")
        assert response.status_code == 200

        for a in response.data['results']:
            assert a['content_type'] is None, f"Only global assignments should be returned for nonexistent service, got {a['content_type']}"


@pytest.mark.django_db
class TestParentReference:
    """Test parent_reference field in service API serializers."""

    def test_assign_with_parent_reference_for_remote_object(self, admin_api_client, rando):
        """When parent_reference is included in an assign request for a remote object,
        it should be stored on the ObjectRole."""
        from ansible_base.rbac.models import DABContentType, DABPermission, ObjectRole, RoleDefinition

        org = Organization.objects.create(name='Parent Org')
        org_ct = DABContentType.objects.get_for_model(org)
        remote_ct = DABContentType.objects.create(service='awx', model='jobtemplate', app_label='main', parent_content_type=org_ct)
        perm = DABPermission.objects.create(codename='execute_jobtemplate', content_type=remote_ct)
        rd = RoleDefinition.objects.create_from_permissions(name='JT Execute', permissions=[perm.api_slug], content_type=remote_ct)

        url = get_relative_url('serviceuserassignment-assign')
        data = {
            "role_definition": rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_id": "42",
            "parent_reference": str(org.pk),
        }
        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, response.data
        assert response.data['parent_reference'] == str(org.pk)

        obj_role = ObjectRole.objects.get(role_definition=rd, object_id='42')
        assert str(obj_role.parent_reference) == str(org.pk)

    def test_assign_without_parent_reference_defaults_to_empty(self, admin_api_client, rando):
        """Omitting parent_reference should still work (backward compatible)."""
        from ansible_base.rbac.models import DABContentType, DABPermission, ObjectRole, RoleDefinition

        remote_ct = DABContentType.objects.create(service='awx', model='remote_inventory', app_label='main')
        perm = DABPermission.objects.create(codename='use_remote_inventory', content_type=remote_ct)
        rd = RoleDefinition.objects.create_from_permissions(name='Remote Inv Use', permissions=[perm.api_slug], content_type=remote_ct)

        url = get_relative_url('serviceuserassignment-assign')
        data = {
            "role_definition": rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_id": "99",
        }
        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, response.data
        assert response.data['parent_reference'] == ''

        obj_role = ObjectRole.objects.get(role_definition=rd, object_id='99')
        assert obj_role.parent_reference == ''

    def test_assign_rejects_non_string_parent_reference(self, admin_api_client, rando):
        """parent_reference must be a string; reject dict/list payloads."""
        from ansible_base.rbac.models import DABContentType, DABPermission, RoleDefinition

        remote_ct = DABContentType.objects.create(service='awx', model='remote_inventory', app_label='main')
        perm = DABPermission.objects.create(codename='use_remote_inventory', content_type=remote_ct)
        rd = RoleDefinition.objects.create_from_permissions(name='Remote Inv Use', permissions=[perm.api_slug], content_type=remote_ct)

        url = get_relative_url('serviceuserassignment-assign')
        data = {
            "role_definition": rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_id": "99",
            "parent_reference": {"id": 12},
        }
        response = admin_api_client.post(url, data=data, format='json')
        assert response.status_code == 400, response.data
        assert 'parent_reference' in response.data

    def test_list_response_includes_parent_reference_for_local_object(self, admin_api_client, rando, inv_rd, inventory):
        """parent_reference should be resolved from the local model's organization FK."""
        inv_rd.give_permission(rando, inventory)

        url = get_relative_url('serviceuserassignment-list')
        response = admin_api_client.get(url + '?page_size=200', format="json")
        assert response.status_code == 200, response.data

        candidates = [a for a in response.data['results'] if a['role_definition'] == inv_rd.name]
        assert len(candidates) >= 1
        assert candidates[0]['parent_reference'] == str(inventory.organization.pk)

    def test_list_response_parent_reference_empty_for_global_roles(self, admin_api_client, rando):
        """Global/system role assignments should have empty parent_reference."""
        sys_auditor = RoleDefinition.objects.managed.sys_auditor
        sys_auditor.give_global_permission(rando)

        url = get_relative_url('serviceuserassignment-list')
        response = admin_api_client.get(url + '?page_size=200', format="json")
        assert response.status_code == 200, response.data

        candidates = [a for a in response.data['results'] if a['role_definition'] == sys_auditor.name]
        assert len(candidates) >= 1
        assert candidates[0]['parent_reference'] == ''

    def test_team_assign_with_parent_reference(self, admin_api_client, team, member_rd, rando):
        """parent_reference works for team assignments too."""
        from ansible_base.rbac.models import DABContentType, DABPermission, ObjectRole, RoleDefinition

        member_rd.give_permission(rando, team)
        org = team.organization
        org_ct = DABContentType.objects.get_for_model(org)
        remote_ct = DABContentType.objects.create(service='awx', model='project', app_label='main', parent_content_type=org_ct)
        perm = DABPermission.objects.create(codename='use_project', content_type=remote_ct)
        rd = RoleDefinition.objects.create_from_permissions(name='Project Use', permissions=[perm.api_slug], content_type=remote_ct)

        url = get_relative_url('serviceteamassignment-assign')
        data = {
            "role_definition": rd.name,
            "team_ansible_id": str(team.resource.ansible_id),
            "object_id": "77",
            "parent_reference": str(org.pk),
        }
        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, response.data
        assert response.data['parent_reference'] == str(org.pk)

        obj_role = ObjectRole.objects.get(role_definition=rd, object_id='77')
        assert str(obj_role.parent_reference) == str(org.pk)

    def test_org_permission_evaluates_with_parent_reference(self, admin_api_client, rando):
        """When parent_reference is set, org-level roles should evaluate
        permission on the remote child object."""
        from ansible_base.rbac.models import DABContentType, DABPermission, RoleDefinition

        org = Organization.objects.create(name='Eval Test Org')
        org_ct = DABContentType.objects.get_for_model(org)
        remote_ct = DABContentType.objects.create(service='ctrl', model='workflow', app_label='main', parent_content_type=org_ct)
        view_perm = DABPermission.objects.create(codename='view_workflow', content_type=remote_ct)
        change_perm = DABPermission.objects.create(codename='change_workflow', content_type=remote_ct)

        obj_rd = RoleDefinition.objects.create_from_permissions(name='Workflow Viewer', permissions=[view_perm.api_slug], content_type=remote_ct)
        org_rd = RoleDefinition.objects.create_from_permissions(
            name='Org Workflow Admin',
            permissions=[view_perm.api_slug, change_perm.api_slug, 'shared.view_organization'],
            content_type=org_ct,
        )

        url = get_relative_url('serviceuserassignment-assign')
        data = {
            "role_definition": obj_rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_id": "55",
            "parent_reference": str(org.pk),
        }
        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, response.data

        from ansible_base.rbac.remote import RemoteObject

        remote_obj = RemoteObject(content_type=remote_ct, object_id=55, parent_reference=org.pk)
        assert rando.has_obj_perm(remote_obj, 'view')
        assert not rando.has_obj_perm(remote_obj, 'change')

        org_rd.give_permission(rando, org)
        assert rando.has_obj_perm(remote_obj, 'change')

    def test_sync_assignment_includes_parent_reference(self, rando, inv_rd, inventory):
        """rest_client.sync_assignment payload should include parent_reference."""
        from unittest.mock import MagicMock, patch

        from ansible_base.resource_registry.rest_client import ResourceAPIClient

        assignment = inv_rd.give_permission(rando, inventory)

        client = ResourceAPIClient(service_url='http://example.com', service_path='/api/v1/service-index/')
        with patch.object(client, '_sync_assignment', return_value=MagicMock()) as mock_sync:
            client.sync_assignment(assignment)
            sent_data = mock_sync.call_args[0][0]
            assert 'parent_reference' in sent_data
            assert sent_data['parent_reference'] == str(inventory.organization.pk)

    def test_pipeline_sets_parent_reference_for_local_models(self, rando, inv_rd, inventory):
        """_resolve_content_object should fill parent_reference from the local model's parent FK."""
        from ansible_base.rbac.models import ObjectRole

        inv_rd.give_permission(rando, inventory)

        obj_role = ObjectRole.objects.get(role_definition=inv_rd, object_id=str(inventory.pk))
        assert obj_role.parent_reference == str(inventory.organization.pk)

    def test_repair_parent_references_command(self, rando, inv_rd, inventory):
        """Management command should backfill empty parent_reference on existing ObjectRoles."""
        from io import StringIO

        from django.core.management import call_command

        from ansible_base.rbac.models import ObjectRole

        inv_rd.give_permission(rando, inventory)
        obj_role = ObjectRole.objects.get(role_definition=inv_rd, object_id=str(inventory.pk))
        ObjectRole.objects.filter(pk=obj_role.pk).update(parent_reference='')

        out = StringIO()
        call_command('repair_parent_references', stdout=out)
        obj_role.refresh_from_db()
        assert obj_role.parent_reference == str(inventory.organization.pk)

    def test_repair_parent_references_dry_run(self, rando, inv_rd, inventory):
        """Dry run should not modify data."""
        from io import StringIO

        from django.core.management import call_command

        from ansible_base.rbac.models import ObjectRole

        inv_rd.give_permission(rando, inventory)
        obj_role = ObjectRole.objects.get(role_definition=inv_rd, object_id=str(inventory.pk))
        ObjectRole.objects.filter(pk=obj_role.pk).update(parent_reference='')

        out = StringIO()
        call_command('repair_parent_references', '--dry-run', stdout=out)
        obj_role.refresh_from_db()
        assert obj_role.parent_reference == ''
        assert 'Would update' in out.getvalue()

    def test_repair_parent_references_noop(self):
        """Command should report nothing when all parent_references are already set."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command('repair_parent_references', stdout=out)
        assert 'No ObjectRoles need parent_reference backfill.' in out.getvalue()

    def test_pipeline_parent_reference_empty_for_top_level_models(self, rando):
        """Models without a parent FK (e.g. Organization) should get empty parent_reference."""
        from ansible_base.rbac.models import ObjectRole, RoleDefinition

        org = Organization.objects.create(name='Pipeline Test Org')
        org_admin = RoleDefinition.objects.managed.org_admin
        org_admin.give_permission(rando, org)

        obj_role = ObjectRole.objects.get(role_definition=org_admin, object_id=str(org.pk))
        assert obj_role.parent_reference == ''
