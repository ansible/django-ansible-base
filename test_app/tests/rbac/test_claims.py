import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import override_settings

from ansible_base.rbac import permission_registry
from ansible_base.rbac.claims import get_claims_hash, get_user_claims, get_user_claims_hashable_form, save_user_claims
from ansible_base.rbac.models import RoleDefinition
from test_app.models import Inventory, Organization, Team


class SharedTestData:
    """Container for all test objects that can be reused across tests"""

    def __init__(self):
        # Create fixed set of objects that all tests share
        self.orgs = self._create_organizations(10)
        self.teams = self._create_teams(20, self.orgs)
        self.inventories = self._create_inventories(15, self.orgs)

        # Static role definitions (created once)
        self.roles = {
            'org_admin': self._get_or_create_org_admin_role(),
            'team_member': self._get_or_create_team_member_role(),
            'platform_auditor': self._get_or_create_platform_auditor_role(),
            'inventory_editor': self._get_or_create_inventory_editor_role(),
        }

    def _create_organizations(self, count: int) -> list[Organization]:
        """Create test organizations"""
        orgs = []
        for i in range(count):
            org = Organization.objects.create(name=f'Test Org {i}')
            orgs.append(org)
        return orgs

    def _create_teams(self, count: int, orgs: list[Organization]) -> list[Team]:
        """Create test teams distributed across organizations"""
        teams = []
        for i in range(count):
            org = orgs[i % len(orgs)]  # distribute teams across orgs
            team = Team.objects.create(name=f'Test Team {i}', organization=org)
            teams.append(team)
        return teams

    def _create_inventories(self, count: int, orgs: list[Organization]) -> list[Inventory]:
        """Create test inventories distributed across organizations"""
        inventories = []
        for i in range(count):
            org = orgs[i % len(orgs)]  # distribute inventories across orgs
            inventory = Inventory.objects.create(name=f'Test Inventory {i}', organization=org)
            inventories.append(inventory)
        return inventories

    def _get_or_create_org_admin_role(self) -> RoleDefinition:
        """Get or create Organization Admin role"""
        try:
            return RoleDefinition.objects.get(name='Organization Admin')
        except RoleDefinition.DoesNotExist:
            return RoleDefinition.objects.create_from_permissions(
                permissions=['view_organization', 'change_organization', 'add_inventory', 'change_inventory', 'delete_inventory', 'view_inventory'],
                name='Organization Admin',
                content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
                managed=True,
            )

    def _get_or_create_team_member_role(self) -> RoleDefinition:
        """Get or create Team Member role"""
        try:
            return RoleDefinition.objects.get(name='Team Member')
        except RoleDefinition.DoesNotExist:
            return RoleDefinition.objects.create_from_permissions(
                permissions=[permission_registry.team_permission, f'view_{permission_registry.team_model._meta.model_name}'],
                name='Team Member',
                content_type=permission_registry.content_type_model.objects.get_for_model(Team),
                managed=True,
            )

    def _get_or_create_platform_auditor_role(self) -> RoleDefinition:
        """Get or create Platform Auditor role"""
        try:
            return RoleDefinition.objects.get(name='Platform Auditor')
        except RoleDefinition.DoesNotExist:
            return RoleDefinition.objects.create_from_permissions(
                permissions=['view_organization', 'view_inventory', 'view_team'],
                name='Platform Auditor',
                content_type=None,  # Global role
                managed=True,
            )

    def _get_or_create_inventory_editor_role(self) -> RoleDefinition:
        """Get or create Inventory Editor role"""
        try:
            return RoleDefinition.objects.get(name='Inventory Editor')
        except RoleDefinition.DoesNotExist:
            return RoleDefinition.objects.create_from_permissions(
                permissions=['change_inventory', 'view_inventory'],
                name='Inventory Editor',
                content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
                managed=True,
            )


class PermissionScenarios:
    """Predefined named permission scenarios"""

    @staticmethod
    def get_scenario_definitions():
        return {
            'no_permissions': {'org_admin': [], 'team_member': [], 'global_roles': []},
            'first_org_only': {'org_admin': [0], 'team_member': [], 'global_roles': []},
            'odds_org_admin': {'org_admin': [1, 3, 5, 7, 9], 'team_member': [], 'global_roles': []},  # odd indexes
            'evens_org_admin': {'org_admin': [0, 2, 4, 6, 8], 'team_member': [], 'global_roles': []},  # even indexes
            'first_three_teams': {'org_admin': [], 'team_member': [0, 1, 2], 'global_roles': []},
            'platform_auditor_only': {'org_admin': [], 'team_member': [], 'global_roles': ['Platform Auditor']},
            'mixed_small': {'org_admin': [0], 'team_member': [2], 'global_roles': ['Platform Auditor']},
            'mixed_large': {'org_admin': [0, 1, 2, 3, 4], 'team_member': [0, 2, 4, 6, 8, 10, 12, 14, 16, 18], 'global_roles': ['Platform Auditor']},
            'all_org_admin': {'org_admin': list(range(10)), 'team_member': [], 'global_roles': []},  # all 10 orgs
            'scattered_permissions': {'org_admin': [1, 7], 'team_member': [3, 9, 15], 'global_roles': ['Platform Auditor']},
            'teams_no_orgs': {'org_admin': [], 'team_member': [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], 'global_roles': []},  # 10 teams, no direct org permissions
        }


class ClaimsScenario:
    """Applies named scenarios and generates expected claims"""

    def __init__(self, test_data: SharedTestData):
        self.test_data = test_data
        self.scenarios = PermissionScenarios.get_scenario_definitions()

    def apply_scenario(self, scenario_name: str, user):
        """Apply a named scenario to a user"""
        if scenario_name not in self.scenarios:
            raise ValueError(f"Unknown scenario: {scenario_name}")

        scenario = self.scenarios[scenario_name]

        # Apply org admin permissions
        for org_idx in scenario['org_admin']:
            org = self.test_data.orgs[org_idx]
            self.test_data.roles['org_admin'].give_permission(user, org)

        # Apply team member permissions
        for team_idx in scenario['team_member']:
            team = self.test_data.teams[team_idx]
            self.test_data.roles['team_member'].give_permission(user, team)

        # Apply global roles
        for role_name in scenario['global_roles']:
            role_key = role_name.lower().replace(' ', '_')
            self.test_data.roles[role_key].give_global_permission(user)

    def get_expected_claims(self, scenario_name: str) -> dict:
        """Generate expected claims for a named scenario"""
        scenario = self.scenarios[scenario_name]
        return self._build_expected_claims(scenario)

    def _build_expected_claims(self, scenario: dict) -> dict:
        """Internal method to build claims structure"""
        claims = {'objects': {'organization': [], 'team': []}, 'object_roles': {}, 'global_roles': sorted(scenario['global_roles'])}

        # Track objects in the order they would be encountered during processing
        org_objects = []  # List of org data in encounter order
        team_objects = []  # List of team data in encounter order
        org_index_map = {}  # ansible_id -> index in org_objects
        team_index_map = {}  # ansible_id -> index in team_objects

        # Process org admin permissions first (they are applied first in apply_scenario)
        if scenario['org_admin']:
            org_indexes = []
            for org_idx in scenario['org_admin']:
                org = self.test_data.orgs[org_idx]
                ansible_id = str(org.resource.ansible_id)

                if ansible_id not in org_index_map:
                    org_index_map[ansible_id] = len(org_objects)
                    org_objects.append({'ansible_id': ansible_id, 'name': org.name})

                org_indexes.append(org_index_map[ansible_id])

            claims['object_roles']['Organization Admin'] = {'content_type': 'organization', 'objects': org_indexes}

        # Process team member permissions second (they are applied second in apply_scenario)
        if scenario['team_member']:
            team_indexes = []
            for team_idx in scenario['team_member']:
                team = self.test_data.teams[team_idx]
                team_ansible_id = str(team.resource.ansible_id)
                org_ansible_id = str(team.organization.resource.ansible_id)

                # Ensure the org exists in org_objects
                if org_ansible_id not in org_index_map:
                    org_index_map[org_ansible_id] = len(org_objects)
                    org_objects.append({'ansible_id': org_ansible_id, 'name': team.organization.name})

                # Add team if not already added
                if team_ansible_id not in team_index_map:
                    team_index_map[team_ansible_id] = len(team_objects)
                    team_objects.append({'ansible_id': team_ansible_id, 'name': team.name, 'org': org_index_map[org_ansible_id]})  # Reference by index

                team_indexes.append(team_index_map[team_ansible_id])

            claims['object_roles']['Team Member'] = {'content_type': 'team', 'objects': team_indexes}

        # Set the final objects arrays
        claims['objects']['organization'] = org_objects
        claims['objects']['team'] = team_objects

        return claims

    def get_expected_hashable_claims(self, scenario_name: str) -> dict:
        """Generate expected hashable claims for a named scenario"""
        scenario = self.scenarios[scenario_name]

        hashable_claims = {'global_roles': sorted(scenario['global_roles']), 'object_roles': {}}

        # Process org admin permissions - collect ansible_ids directly
        if scenario['org_admin']:
            org_ansible_ids = []
            for org_idx in scenario['org_admin']:
                org = self.test_data.orgs[org_idx]
                org_ansible_ids.append(str(org.resource.ansible_id))

            # Sort ansible_ids for deterministic ordering
            hashable_claims['object_roles']['Organization Admin'] = sorted(org_ansible_ids)

        # Process team member permissions - collect ansible_ids directly
        if scenario['team_member']:
            team_ansible_ids = []
            for team_idx in scenario['team_member']:
                team = self.test_data.teams[team_idx]
                team_ansible_ids.append(str(team.resource.ansible_id))

            # Sort ansible_ids for deterministic ordering
            hashable_claims['object_roles']['Team Member'] = sorted(team_ansible_ids)

        return hashable_claims


@pytest.mark.django_db
class TestUserClaims:
    @pytest.fixture
    def shared_test_data(self, db):
        """Shared test data for all tests in this class"""
        return SharedTestData()

    @pytest.fixture
    def claims_scenario(self, shared_test_data):
        return ClaimsScenario(shared_test_data)

    @pytest.mark.parametrize("scenario_name", list(PermissionScenarios.get_scenario_definitions().keys()))
    def test_claims_scenarios(self, claims_scenario, scenario_name):
        """Test various permission scenarios produce correct claims"""
        user = get_user_model().objects.create(username=f'test_user_{scenario_name}')

        # Apply the named scenario
        claims_scenario.apply_scenario(scenario_name, user)

        # Get expected claims for this scenario
        expected_claims = claims_scenario.get_expected_claims(scenario_name)

        # Test the actual function
        actual_claims = get_user_claims(user)

        assert actual_claims == expected_claims

    @pytest.mark.parametrize("scenario_name", list(PermissionScenarios.get_scenario_definitions().keys()))
    def test_hashable_claims_scenarios(self, claims_scenario, scenario_name):
        """Test various permission scenarios produce correct hashable claims"""
        user = get_user_model().objects.create(username=f'test_hashable_user_{scenario_name}')

        # Apply the named scenario
        claims_scenario.apply_scenario(scenario_name, user)

        # Get expected hashable claims for this scenario
        expected_hashable_claims = claims_scenario.get_expected_hashable_claims(scenario_name)

        # Get the user's claims and convert to hashable form
        user_claims = get_user_claims(user)
        actual_hashable_claims = get_user_claims_hashable_form(user_claims)

        assert actual_hashable_claims == expected_hashable_claims

    @pytest.mark.parametrize("scenario_name", list(PermissionScenarios.get_scenario_definitions().keys()))
    def test_identical_permissions_same_hash(self, claims_scenario, scenario_name):
        """Test that two users with identical permissions produce the same hash"""
        # Create two different users
        user1 = get_user_model().objects.create(username=f'test_hash_user1_{scenario_name}')
        user2 = get_user_model().objects.create(username=f'test_hash_user2_{scenario_name}')

        # Apply the same scenario to both users
        claims_scenario.apply_scenario(scenario_name, user1)
        claims_scenario.apply_scenario(scenario_name, user2)

        # Get claims for both users
        user1_claims = get_user_claims(user1)
        user2_claims = get_user_claims(user2)

        # Convert to hashable form
        user1_hashable = get_user_claims_hashable_form(user1_claims)
        user2_hashable = get_user_claims_hashable_form(user2_claims)

        # Generate hashes
        user1_hash = get_claims_hash(user1_hashable)
        user2_hash = get_claims_hash(user2_hashable)

        # Verify hashes are identical
        assert user1_hash == user2_hash

        # Verify hash is a valid SHA-256 hex string (64 characters)
        assert len(user1_hash) == 64
        assert all(c in '0123456789abcdef' for c in user1_hash)

    @pytest.mark.parametrize("scenario_name", list(PermissionScenarios.get_scenario_definitions().keys()))
    def test_serialize_and_save_claims(self, claims_scenario, scenario_name):
        """Test that serialized claims from first user can be saved to second user"""
        # Create two different users
        user1 = get_user_model().objects.create(username=f'test_hash_user1_{scenario_name}')
        user2 = get_user_model().objects.create(username=f'test_hash_user2_{scenario_name}')

        # Apply the same scenario to both users
        claims_scenario.apply_scenario(scenario_name, user1)

        # Get claims for the first user
        user1_claims = get_user_claims(user1)
        # Claims for second user should be nothing
        assert get_user_claims(user2) == {'global_roles': [], 'object_roles': {}, 'objects': {'organization': [], 'team': []}}

        # Save the claims for user2
        save_user_claims(user2, **user1_claims)
        user2_claims = get_user_claims(user2)

        # Verify claims match, users should now have same permissions
        assert user1_claims == user2_claims

        # Convert to hashable form
        user1_hashable = get_user_claims_hashable_form(user1_claims)
        user2_hashable = get_user_claims_hashable_form(user2_claims)

        # Generate hashes
        user1_hash = get_claims_hash(user1_hashable)
        user2_hash = get_claims_hash(user2_hashable)

        # Verify hashes are identical
        assert user1_hash == user2_hash

    @pytest.mark.parametrize("scenario_name", list(PermissionScenarios.get_scenario_definitions().keys()))
    def test_rebuild_single_user(self, claims_scenario, scenario_name):
        """Get claims hash, then just delete everything and save_user_claims should build it back up"""
        user = get_user_model().objects.create(username=f'test_hash_user1_{scenario_name}')

        # Apply the scenario
        claims_scenario.apply_scenario(scenario_name, user)

        # Save the claims to reapply later
        user_claims = get_user_claims(user)
        claims_hash = get_claims_hash(get_user_claims_hashable_form(user_claims))

        # Rage delete everything
        for team in Team.objects.all():
            team.delete()

        for org in Organization.objects.all():
            org.delete()

        # If we deleted everything, the current object-related claims should be empty
        # The global roles might still have some content, we do not care here
        wrecked_user_claims = get_user_claims(user)
        assert wrecked_user_claims['objects'] == {'organization': [], 'team': []}  # we deleted them all
        assert wrecked_user_claims['object_roles'] == {}

        # Save the old claims, should rebuild all the objects, potentially complex operation, highly abstracted here
        save_user_claims(user, **user_claims)

        # Now that everything is created anew, claims should match
        assert get_user_claims(user) == user_claims

        # Verify current claims hash also matches
        assert get_claims_hash(get_user_claims_hashable_form(get_user_claims(user))) == claims_hash

    @override_settings(DEBUG=True)
    def test_claims_query_performance_baseline(self, claims_scenario):
        """Performance test to measure database queries for claims generation.

        This test establishes a baseline for the number of database queries
        used when generating claims for the 'mixed_large' scenario, which is
        one of the most complex permission scenarios.

        Scenario details:
        - Organization Admin for 5 organizations (indexes 0,1,2,3,4)
        - Team Member for 10 teams (indexes 0,2,4,6,8,10,12,14,16,18)
        - Platform Auditor global role
        """
        scenario_name = 'mixed_large'

        # Create user and apply the complex scenario
        user = get_user_model().objects.create(username='test_user_performance')
        claims_scenario.apply_scenario(scenario_name, user)

        # Clear any existing queries from setup
        connection.queries_log.clear()

        # Count queries before claims generation
        queries_before = len(connection.queries)

        # Generate claims (this is what we're measuring)
        user_claims = get_user_claims(user)

        # Count queries after claims generation
        queries_after = len(connection.queries)
        total_queries = queries_after - queries_before

        # Verify we got valid claims (basic sanity check)
        assert isinstance(user_claims, dict)
        assert 'objects' in user_claims
        assert 'object_roles' in user_claims
        assert 'global_roles' in user_claims

        # Report the baseline query count
        print("\n=== CLAIMS QUERY PERFORMANCE BASELINE ===")
        print(f"Scenario: {scenario_name}")
        print(f"Total database queries: {total_queries}")
        print("Query details:")
        for i, query in enumerate(connection.queries[queries_before:], 1):
            print(f"  {i}. {query['sql'][:100]}{'...' if len(query['sql']) > 100 else ''}")
            print(f"     Time: {query['time']}s")
        print("=" * 45)

        # Assert we maintain our improved performance baseline
        # Baseline improved after N+1 fix: 4 queries for the mixed_large scenario
        # (Even more efficient: team organization resolution optimized with single join query)
        assert total_queries == 4, f"Claims generation used {total_queries} queries, expected 4 (improved baseline)"

    @override_settings(DEBUG=True)
    def test_claims_query_teams_no_orgs_efficient(self, claims_scenario):
        """Test that team organization resolution is efficient after N+1 fix.

        This test verifies that when a user has team permissions but no direct
        organization permissions, the claims generation is still efficient.

        The fix: Include 'organization__name' in the team query to get all needed
        data in a single query instead of individual org lookups.

        Scenario details:
        - Team Member for 10 teams (indexes 0,1,2,3,4,5,6,7,8,9)
        - NO Organization Admin permissions
        - Teams are distributed across 10 different organizations

        Expected: Efficient bulk query gets team + organization data together
        Query count: 4 (even better than the 6-query baseline!)
        """
        scenario_name = 'teams_no_orgs'

        # Create user and apply the scenario
        user = get_user_model().objects.create(username='test_user_teams_efficient')
        claims_scenario.apply_scenario(scenario_name, user)

        # Clear any existing queries from setup
        connection.queries_log.clear()

        # Count queries before claims generation
        queries_before = len(connection.queries)

        # Generate claims (this is what we're measuring)
        user_claims = get_user_claims(user)

        # Count queries after claims generation
        queries_after = len(connection.queries)
        total_queries = queries_after - queries_before

        # Verify we got valid claims (basic sanity check)
        assert isinstance(user_claims, dict)
        assert 'objects' in user_claims
        assert 'object_roles' in user_claims
        assert 'global_roles' in user_claims

        # Verify we have team permissions but no direct org permissions
        assert 'Team Member' in user_claims['object_roles']
        assert 'Organization Admin' not in user_claims['object_roles']
        assert len(user_claims['objects'].get('team', [])) == 10  # 10 teams
        assert len(user_claims['objects'].get('organization', [])) == 10  # 10 orgs (added during resolution)

        # Report the successful fix
        print("\n=== TEAMS_NO_ORGS N+1 PROBLEM FIXED ===")
        print(f"Scenario: {scenario_name}")
        print(f"Total database queries: {total_queries}")
        print("Query details:")
        for i, query in enumerate(connection.queries[queries_before:], 1):
            print(f"  {i}. {query['sql'][:100]}{'...' if len(query['sql']) > 100 else ''}")
            print(f"     Time: {query['time']}s")
        print("=" * 45)

        # Assert the fix worked - even better performance than baseline!
        assert total_queries == 4, f"Claims generation used {total_queries} queries, expected 4 (N+1 problem fixed!)"
