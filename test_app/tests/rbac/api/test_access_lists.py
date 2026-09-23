import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import RoleDefinition
from test_app.models import Team, User


@pytest.mark.django_db
def test_user_access_list(admin_api_client, inv_rd, org_inv_rd, inventory, member_rd):
    url = get_relative_url('role-user-access', kwargs={'pk': inventory.pk, 'model_name': 'aap.inventory'})

    u1 = User.objects.create(username='direct-inv-access', first_name='user', last_name='one')
    inv_rd.give_permission(u1, inventory)

    u2 = User.objects.create(username='org-level-access')
    org_inv_rd.give_permission(u2, inventory.organization)

    u3 = User.objects.create(username='team-via-access')
    team = Team.objects.create(name='proxy-team', organization=inventory.organization)
    inv_rd.give_permission(team, inventory)
    member_rd.give_permission(u3, team)

    response = admin_api_client.get(url)
    assert response.status_code == 200

    user_data = {}
    for user_detail in response.data['results']:
        user_data[user_detail['username']] = user_detail['object_role_assignments']
        assert 'related' in user_detail
        assert 'details' in user_detail['related']
        detail_resp = admin_api_client.get(user_detail['related']['details'])
        assert detail_resp.status_code == 200, detail_resp.data
        # This should have the same entries in a list view as the access list had in the assignments list
        assert detail_resp.data['count'] == len(user_detail['object_role_assignments'])
        if user_detail['username'] == u1.username:
            assert user_detail['first_name'] == 'user'
            assert user_detail['last_name'] == 'one'

    assert u1.username in user_data
    assert len(user_data[u1.username]) == 1
    assert user_data[u1.username][0]['type'] == 'direct'

    assert u2.username in user_data
    assert len(user_data[u2.username]) == 1
    assert user_data[u2.username][0]['type'] == 'indirect'

    assert u3.username in user_data
    assert len(user_data[u3.username]) == 1
    assert user_data[u3.username][0]['type'] == 'team'


@pytest.mark.django_db
def test_team_access_list(admin_api_client, inv_rd, org_inv_rd, inventory):
    url = get_relative_url('role-team-access', kwargs={'pk': inventory.pk, 'model_name': 'aap.inventory'})

    t1 = Team.objects.create(name='org-access', organization=inventory.organization)
    org_inv_rd.give_permission(t1, inventory.organization)

    t2 = Team.objects.create(name='direct-access', organization=inventory.organization)
    inv_rd.give_permission(t2, inventory)

    response = admin_api_client.get(url)
    assert response.status_code == 200

    team_data = {}
    for team_detail in response.data['results']:
        team_data[team_detail['name']] = team_detail['object_role_assignments']

        assert 'related' in team_detail
        assert 'details' in team_detail['related']
        detail_resp = admin_api_client.get(team_detail['related']['details'])
        assert detail_resp.status_code == 200, detail_resp.data
        # This should have the same entries in a list view as the access list had in the assignments list
        assert detail_resp.data['count'] == len(team_detail['object_role_assignments'])

    assert t1.name in team_data
    assert len(team_data[t1.name]) == 1
    assert team_data[t1.name][0]['type'] == 'indirect'

    assert t2.name in team_data
    assert len(team_data[t2.name]) == 1
    assert team_data[t2.name][0]['type'] == 'direct'


@pytest.mark.django_db
def test_intermediary_role_display(admin_api_client, inventory, organization, member_rd, rando):
    team = Team.objects.create(name='has_org_roles', organization=inventory.organization)

    org_admin_inv_rd = RoleDefinition.objects.create_from_permissions(
        permissions=['view_organization', 'add_inventory', 'change_inventory', 'delete_inventory', 'view_inventory'],
        name='org-inv-admin-rd',
        content_type=permission_registry.content_type_model.objects.get_for_model(organization),
    )
    org_view_inv_rd = RoleDefinition.objects.create_from_permissions(
        permissions=['view_organization', 'view_inventory'],
        name='org-inv-view-rd',
        content_type=permission_registry.content_type_model.objects.get_for_model(organization),
    )

    org_admin_inv_rd.give_permission(team, inventory.organization)
    org_view_inv_rd.give_permission(team, inventory.organization)
    member_rd.give_permission(rando, team)

    url = get_relative_url('role-user-access-assignments', kwargs={'pk': inventory.pk, 'model_name': 'aap.inventory', 'actor_pk': rando.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200, response.data

    assert response.data['count'] == 1
    assignment = response.data['results'][0]

    assert 'intermediary_roles' in assignment
    intermediary = assignment['intermediary_roles']
    assert len(intermediary) == 2
    intermediary_names = [entry['role_definition']['name'] for entry in intermediary]
    assert org_admin_inv_rd.name in intermediary_names
    assert org_view_inv_rd.name in intermediary_names


@pytest.mark.django_db
def test_no_duplicates(rando, inv_rd, inventory, org_inv_rd, admin_api_client):
    inv_rd.give_permission(rando, inventory)
    org_inv_rd.give_permission(rando, inventory.organization)

    # the admin user themselves will show up, so filter superusers out
    url = get_relative_url('role-user-access', kwargs={'pk': inventory.pk, 'model_name': 'aap.inventory'}) + '?is_superuser=false'
    response = admin_api_client.get(url)
    assert response.status_code == 200, response.data
    assert response.data['count'] == 1, response.data


@pytest.mark.django_db
def test_no_duplicates_team(team, inv_rd, inventory, org_inv_rd, admin_api_client):
    inv_rd.give_permission(team, inventory)
    org_inv_rd.give_permission(team, inventory.organization)

    url = get_relative_url('role-team-access', kwargs={'pk': inventory.pk, 'model_name': 'aap.inventory'})
    response = admin_api_client.get(url)
    assert response.status_code == 200, response.data
    assert response.data['count'] == 1, response.data


@pytest.mark.django_db
def test_user_access_list_permission_filtered(admin_api_client, global_inv_rd, inventory):
    """Test user access list when URL uses a permission slug instead of a content type slug.

    Uses a global role assignment so the user is found via global_exists, not obj_exists."""
    url = get_relative_url('role-user-access', kwargs={'pk': inventory.pk, 'model_name': 'aap.view_inventory'})

    u1 = User.objects.create(username='global-perm-user')
    global_inv_rd.give_global_permission(u1)

    response = admin_api_client.get(url)
    assert response.status_code == 200
    usernames = [u['username'] for u in response.data['results']]
    assert u1.username in usernames


@pytest.mark.django_db
def test_org_admin_role_user_access_bug(organization, org_admin_rd):
    """
    Test for AAP-52187: Org admin gets 403 on role_user_access despite having proper permissions.

    This test demonstrates the RBAC evaluation bug where:
    - Org admin can GET /organizations/X/ (works correctly)
    - Same org admin gets 403 on /role_user_access/shared.organization/X/ (bug)
    - Both should work since the user has shared.view_organization permission
    """
    from rest_framework.test import APIClient

    # Create org admin user for AAP-52187 reproduction
    org_admin_user = User.objects.create(username='aap52187-org-admin-test-user')

    # Give user Organization Admin role on the organization
    org_admin_rd.give_permission(org_admin_user, organization)

    # Create API client for the org admin user
    client = APIClient()
    client.force_authenticate(user=org_admin_user)

    # Test 1: Org admin should be able to view the organization directly
    org_detail_url = get_relative_url('organization-detail', kwargs={'pk': organization.pk})
    response = client.get(org_detail_url)
    assert response.status_code == 200, f"Org admin should be able to view organization directly: {response.data}"

    # Test 2: Org admin should be able to view role user access for the same organization
    # This is currently broken due to has_obj_perm evaluation bug in UserAccessViewSet
    role_access_url = get_relative_url('role-user-access', kwargs={'pk': organization.pk, 'model_name': 'shared.organization'})
    response = client.get(role_access_url)

    # This assertion will fail with current bug, demonstrating the issue
    assert response.status_code == 200, (
        f"AAP-52187 BUG: Org admin should be able to view role access for organization they manage. "
        f"User has shared.view_organization permission and can access org detail endpoint, "
        f"but role_user_access fails with: {response.status_code} {response.data}"
    )


@pytest.mark.django_db
def test_prefetch_team_assignment_type(admin_api_client, inv_rd, inventory, member_rd):
    """The bulk prefetch classifies team-member-based assignments as 'team' type."""
    user = User.objects.create(username='team-type-user')
    team = Team.objects.create(name='team-type-team', organization=inventory.organization)
    inv_rd.give_permission(team, inventory)
    member_rd.give_permission(user, team)

    url = get_relative_url('role-user-access', kwargs={'pk': inventory.pk, 'model_name': 'aap.inventory'}) + '?is_superuser=false'
    response = admin_api_client.get(url)
    assert response.status_code == 200

    user_entry = next(r for r in response.data['results'] if r['username'] == 'team-type-user')
    assert len(user_entry['object_role_assignments']) == 1
    assert user_entry['object_role_assignments'][0]['type'] == 'team'


@pytest.mark.django_db
def test_prefetch_indirect_assignment_type(admin_api_client, org_inv_rd, inventory):
    """The bulk prefetch classifies org-level role assignments as 'indirect' type."""
    user = User.objects.create(username='indirect-type-user')
    org_inv_rd.give_permission(user, inventory.organization)

    url = get_relative_url('role-user-access', kwargs={'pk': inventory.pk, 'model_name': 'aap.inventory'}) + '?is_superuser=false'
    response = admin_api_client.get(url)
    assert response.status_code == 200

    user_entry = next(r for r in response.data['results'] if r['username'] == 'indirect-type-user')
    assert len(user_entry['object_role_assignments']) == 1
    assert user_entry['object_role_assignments'][0]['type'] == 'indirect'


@pytest.mark.django_db
def test_prefetch_fallback_without_parent(inv_rd, inventory):
    """get_object_role_assignments falls back to per-user queries when self.parent is None."""
    from rest_framework import serializers as drf_serializers

    from ansible_base.rbac.api.serializers import UserAccessListMixin
    from ansible_base.rbac.models import DABContentType

    user = User.objects.create(username='fallback-user')
    inv_rd.give_permission(user, inventory)
    ct = DABContentType.objects.get_for_model(type(inventory))

    class TestSerializer(UserAccessListMixin, drf_serializers.ModelSerializer):
        class Meta:
            model = User
            fields = ['id']

    serializer = TestSerializer(
        context={
            'related_object': inventory,
            'permission': None,
            'content_type': ct,
        }
    )
    assert serializer.parent is None
    assignments = serializer.get_object_role_assignments(user)
    assert len(assignments) == 1
    assert assignments[0]['type'] == 'direct'


@pytest.mark.django_db
def test_user_access_list_query_count(admin_api_client, inv_rd, inventory):
    """Query count should not scale with the number of users in the result.
    With prefetched assignments, going from 2 to 20 users should add at most
    a handful of queries, not 18 extra (one per additional user)."""
    url = get_relative_url('role-user-access', kwargs={'pk': inventory.pk, 'model_name': 'aap.inventory'})

    # Measure with 2 users
    for i in range(2):
        u = User.objects.create(username=f'query-count-user-{i}')
        inv_rd.give_permission(u, inventory)

    admin_api_client.get(url)  # warm up
    with CaptureQueriesContext(connection) as ctx_small:
        response = admin_api_client.get(url)
    assert response.status_code == 200
    queries_small = len(ctx_small.captured_queries)

    # Add 18 more users (20 total)
    for i in range(2, 20):
        u = User.objects.create(username=f'query-count-user-{i}')
        inv_rd.give_permission(u, inventory)

    admin_api_client.get(url)  # warm up
    with CaptureQueriesContext(connection) as ctx_large:
        response = admin_api_client.get(url)
    assert response.status_code == 200
    queries_large = len(ctx_large.captured_queries)

    added_queries = queries_large - queries_small
    assert added_queries < 5, (
        f"Adding 18 users increased query count by {added_queries} "
        f"({queries_small} -> {queries_large}). "
        f"object_role_assignments may be doing per-user queries."
    )


@pytest.mark.django_db
def test_team_access_list_query_count(admin_api_client, inv_rd, inventory):
    """Query count should not scale with the number of teams in the result.
    With prefetched assignments, going from 2 to 20 teams should add at most
    a handful of queries, not 18 extra (one per additional team)."""
    url = get_relative_url('role-team-access', kwargs={'pk': inventory.pk, 'model_name': 'aap.inventory'})

    # Measure with 2 teams
    for i in range(2):
        t = Team.objects.create(name=f'query-count-team-{i}', organization=inventory.organization)
        inv_rd.give_permission(t, inventory)

    admin_api_client.get(url)  # warm up
    with CaptureQueriesContext(connection) as ctx_small:
        response = admin_api_client.get(url)
    assert response.status_code == 200
    queries_small = len(ctx_small.captured_queries)

    # Add 18 more teams (20 total)
    for i in range(2, 20):
        t = Team.objects.create(name=f'query-count-team-{i}', organization=inventory.organization)
        inv_rd.give_permission(t, inventory)

    admin_api_client.get(url)  # warm up
    with CaptureQueriesContext(connection) as ctx_large:
        response = admin_api_client.get(url)
    assert response.status_code == 200
    queries_large = len(ctx_large.captured_queries)

    added_queries = queries_large - queries_small
    assert added_queries < 5, (
        f"Adding 18 teams increased query count by {added_queries} "
        f"({queries_small} -> {queries_large}). "
        f"object_role_assignments may be doing per-team queries."
    )
