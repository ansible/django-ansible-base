"""Tests for EvaluationsPrefetch, EvaluationUpdates, and the batched recompute path."""

from unittest import mock

import pytest
from django.test.utils import CaptureQueriesContext

from ansible_base.rbac import permission_registry
from ansible_base.rbac.caching import EvaluationUpdates, recompute_all_role_evaluations, recompute_role_evaluations
from ansible_base.rbac.models import ObjectRole, RoleDefinition, RoleEvaluation, RoleEvaluationUUID
from ansible_base.rbac.prefetch import EvaluationsPrefetch, TypesPrefetch
from test_app.models import Inventory, Organization, Team, UUIDModel


@pytest.fixture
def org_inv_rd():
    return RoleDefinition.objects.create_from_permissions(
        permissions=['view_organization', 'view_inventory', 'change_inventory'],
        name='test-org-inv-rd',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
    )


class TestEvaluationsPrefetch:
    @pytest.mark.django_db
    def test_partials_loaded(self, org_inv_rd, rando):
        """EvaluationsPrefetch loads existing evaluation data by role PK."""
        org = Organization.objects.create(name='ep_test_org')
        org_inv_rd.give_permission(rando, org)

        roles = list(ObjectRole.objects.filter(object_id=str(org.pk)))
        assert len(roles) > 0
        ep = EvaluationsPrefetch.from_roles(roles)

        for role in roles:
            partials = ep.get_partials(role.pk)
            expected = {}
            for eval_id, codename, ct_id, obj_id in role.permission_partials.values_list('id', 'codename', 'content_type_id', 'object_id'):
                expected[(codename, ct_id, obj_id)] = eval_id
            assert partials == expected

    @pytest.mark.django_db
    def test_empty_partials_for_unknown_role(self):
        """get_partials returns empty dict for a role PK not in the batch."""
        ep = EvaluationsPrefetch()
        assert ep.get_partials(99999) == {}
        assert ep.get_partials_uuid(99999) == {}
        assert ep.get_team_roles(99999) == []

    @pytest.mark.django_db
    def test_no_per_role_queries_with_prefetch(self, org_inv_rd, rando):
        """Using EvaluationsPrefetch avoids per-role evaluation queries."""
        org = Organization.objects.create(name='no_query_org')
        org_inv_rd.give_permission(rando, org)

        types_prefetch = TypesPrefetch.from_db()
        roles = list(ObjectRole.objects.filter(object_id=str(org.pk)))
        ep = EvaluationsPrefetch.from_roles(roles)

        from django.db import connection

        with CaptureQueriesContext(connection) as ctx:
            for role in roles:
                role.needed_cache_updates(types_prefetch=types_prefetch, evaluations_prefetch=ep)

        partials_queries = [q for q in ctx.captured_queries if 'dab_rbac_roleevaluation' in q['sql'] and 'SELECT' in q['sql']]
        assert len(partials_queries) == 0, "With EvaluationsPrefetch, no per-role RoleEvaluation queries should occur"

    @pytest.mark.django_db
    def test_values_list_fallback_without_prefetch(self, org_inv_rd, rando):
        """Without EvaluationsPrefetch, needed_cache_updates falls back to per-role queries."""
        org = Organization.objects.create(name='fallback_org')
        org_inv_rd.give_permission(rando, org)

        types_prefetch = TypesPrefetch.from_db()
        roles = list(ObjectRole.objects.filter(object_id=str(org.pk)))

        from django.db import connection

        with CaptureQueriesContext(connection) as ctx:
            for role in roles:
                role.needed_cache_updates(types_prefetch=types_prefetch)

        partials_queries = [q for q in ctx.captured_queries if 'dab_rbac_roleevaluation' in q['sql'] and 'SELECT' in q['sql']]
        assert len(partials_queries) > 0, "Without prefetch, should fall back to per-role queries"

    @pytest.mark.django_db
    def test_prefetch_and_fallback_produce_same_result(self, org_inv_rd, rando):
        """EvaluationsPrefetch and fallback paths return identical results."""
        org = Organization.objects.create(name='consistency_org')
        for i in range(3):
            Inventory.objects.create(name=f'consistency_inv_{i}', organization=org)
        org_inv_rd.give_permission(rando, org)

        types_prefetch = TypesPrefetch.from_db()

        role = ObjectRole.objects.filter(object_id=str(org.pk)).first()
        to_delete_fallback, to_add_fallback = role.needed_cache_updates(types_prefetch=types_prefetch)

        ep = EvaluationsPrefetch.from_roles([role])
        to_delete_ep, to_add_ep = role.needed_cache_updates(types_prefetch=types_prefetch, evaluations_prefetch=ep)

        assert to_delete_fallback == to_delete_ep
        assert set((e.codename, e.content_type_id, e.object_id) for e in to_add_fallback) == set(
            (e.codename, e.content_type_id, e.object_id) for e in to_add_ep
        )


class TestEvaluationsPrefetchTeamRoles:
    @pytest.mark.django_db
    def test_team_roles_loaded(self, member_rd, rando):
        """provides_teams -> has_roles chain is batch-loaded correctly."""
        org = Organization.objects.create(name='team_roles_org')
        team = Team.objects.create(name='team_roles_team', organization=org)
        inv = Inventory.objects.create(name='team_roles_inv', organization=org)
        inv_rd = RoleDefinition.objects.create_from_permissions(
            permissions=['view_inventory'],
            name='test-inv-view',
            content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
        )
        member_assignment = member_rd.give_permission(rando, team)
        inv_rd.give_permission(team, inv)

        member_role = member_assignment.object_role
        assert member_role.provides_teams.exists()

        ep = EvaluationsPrefetch.from_roles([member_role])
        team_roles = ep.get_team_roles(member_role.pk)

        expected_pks = set()
        for t in member_role.provides_teams.all():
            for tr in t.has_roles.all():
                expected_pks.add(tr.pk)
        assert len(expected_pks) > 0
        assert set(r.pk for r in team_roles) == expected_pks

    @pytest.mark.django_db
    def test_team_roles_empty_when_no_teams(self, org_inv_rd, rando):
        """Roles without provides_teams get an empty team_roles list."""
        org = Organization.objects.create(name='no_teams_org')
        org_inv_rd.give_permission(rando, org)

        roles = list(ObjectRole.objects.filter(object_id=str(org.pk)))
        ep = EvaluationsPrefetch.from_roles(roles)
        for role in roles:
            assert ep.get_team_roles(role.pk) == []

    @pytest.mark.django_db
    def test_from_roles_with_empty_list(self):
        """from_roles with no roles produces an empty prefetch."""
        ep = EvaluationsPrefetch.from_roles([])
        assert ep.get_partials(1) == {}
        assert ep.get_partials_uuid(1) == {}
        assert ep.get_team_roles(1) == []

    @pytest.mark.django_db
    def test_multiple_roles_independent(self, org_inv_rd, rando):
        """Partials from different roles don't bleed into each other."""
        org1 = Organization.objects.create(name='iso_org_1')
        org2 = Organization.objects.create(name='iso_org_2')
        Inventory.objects.create(name='iso_inv_1', organization=org1)
        org_inv_rd.give_permission(rando, org1)
        org_inv_rd.give_permission(rando, org2)

        role1 = ObjectRole.objects.get(object_id=str(org1.pk), role_definition=org_inv_rd)
        role2 = ObjectRole.objects.get(object_id=str(org2.pk), role_definition=org_inv_rd)
        ep = EvaluationsPrefetch.from_roles([role1, role2])

        partials1 = ep.get_partials(role1.pk)
        partials2 = ep.get_partials(role2.pk)
        assert len(partials1) > len(partials2), "org1 has an inventory child, org2 does not"
        assert set(partials1.keys()).isdisjoint(set(partials2.keys())), "No overlap between different roles' partials"


class TestEvaluationUpdates:
    @pytest.mark.django_db
    def test_apply_empty_is_noop(self):
        """apply() with nothing collected doesn't touch the database."""
        updates = EvaluationUpdates()
        from django.db import connection

        with CaptureQueriesContext(connection) as ctx:
            updates.apply()
        assert len(ctx.captured_queries) == 0

    @pytest.mark.django_db
    def test_collect_accumulates_across_roles(self, org_inv_rd, rando):
        """Collecting from multiple roles accumulates into the same instance."""
        org1 = Organization.objects.create(name='accum_org_1')
        org2 = Organization.objects.create(name='accum_org_2')
        org_inv_rd.give_permission(rando, org1)
        org_inv_rd.give_permission(rando, org2)

        types_prefetch = TypesPrefetch.from_db()
        RoleEvaluation.objects.all().delete()

        updates = EvaluationUpdates()
        role1 = ObjectRole.objects.get(object_id=str(org1.pk), role_definition=org_inv_rd)
        role2 = ObjectRole.objects.get(object_id=str(org2.pk), role_definition=org_inv_rd)
        updates.collect(role1, types_prefetch)
        updates.collect(role2, types_prefetch)

        assert len(updates.to_add) > 0
        role_ids_in_adds = set(e.role_id for e in updates.to_add)
        assert role1.pk in role_ids_in_adds
        assert role2.pk in role_ids_in_adds

    @pytest.mark.django_db
    def test_apply_creates_evaluations(self, org_inv_rd, rando):
        """apply() actually writes the accumulated evaluations to the database."""
        org = Organization.objects.create(name='apply_org')
        Inventory.objects.create(name='apply_inv', organization=org)
        org_inv_rd.give_permission(rando, org)

        types_prefetch = TypesPrefetch.from_db()
        role = ObjectRole.objects.get(object_id=str(org.pk), role_definition=org_inv_rd)
        original_count = RoleEvaluation.objects.filter(role=role).count()
        assert original_count > 0

        RoleEvaluation.objects.filter(role=role).delete()
        assert RoleEvaluation.objects.filter(role=role).count() == 0

        updates = EvaluationUpdates()
        updates.collect(role, types_prefetch)
        updates.apply()

        assert RoleEvaluation.objects.filter(role=role).count() == original_count

    @pytest.mark.django_db
    def test_apply_deletes_stale_evaluations(self, org_inv_rd, rando):
        """apply() removes evaluations that are no longer expected."""
        org = Organization.objects.create(name='stale_org')
        org_inv_rd.give_permission(rando, org)

        role = ObjectRole.objects.get(object_id=str(org.pk), role_definition=org_inv_rd)
        inv_ct = permission_registry.content_type_model.objects.get_for_model(Inventory)
        stale = RoleEvaluation.objects.create(role=role, codename='view_inventory', content_type_id=inv_ct.id, object_id=999999)
        assert RoleEvaluation.objects.filter(pk=stale.pk).exists()

        types_prefetch = TypesPrefetch.from_db()
        updates = EvaluationUpdates()
        updates.collect(role, types_prefetch)
        assert len(updates.to_delete) > 0
        updates.apply()

        assert not RoleEvaluation.objects.filter(pk=stale.pk).exists()

    @pytest.mark.django_db
    def test_collect_with_evaluations_prefetch(self, org_inv_rd, rando):
        """collect() works correctly when given an EvaluationsPrefetch."""
        org = Organization.objects.create(name='ep_collect_org')
        Inventory.objects.create(name='ep_collect_inv', organization=org)
        org_inv_rd.give_permission(rando, org)

        types_prefetch = TypesPrefetch.from_db()
        role = ObjectRole.objects.get(object_id=str(org.pk), role_definition=org_inv_rd)

        updates_fallback = EvaluationUpdates()
        updates_fallback.collect(role, types_prefetch)

        ep = EvaluationsPrefetch.from_roles([role])
        updates_prefetch = EvaluationUpdates()
        updates_prefetch.collect(role, types_prefetch, evaluations_prefetch=ep)

        assert updates_fallback.to_delete == updates_prefetch.to_delete
        assert set((e.codename, e.content_type_id, e.object_id) for e in updates_fallback.to_add) == set(
            (e.codename, e.content_type_id, e.object_id) for e in updates_prefetch.to_add
        )


class TestComputeObjectRolePermissionsQueryReduction:
    @pytest.mark.django_db
    def test_full_recompute_uses_fewer_queries_than_iterator(self, org_inv_rd, rando):
        """The batched EvaluationsPrefetch default path should use fewer queries
        than the old .iterator() approach for a non-trivial number of ObjectRoles."""
        orgs = [Organization.objects.create(name=f'qr_org_{i}') for i in range(5)]
        for org in orgs:
            for j in range(3):
                Inventory.objects.create(name=f'qr_inv_{org.name}_{j}', organization=org)

        for org in orgs:
            org_inv_rd.give_permission(rando, org)

        n_roles = ObjectRole.objects.count()
        assert n_roles >= 5

        from django.db import connection

        types_prefetch = TypesPrefetch.from_db()
        RoleEvaluation.objects.all().delete()
        RoleEvaluationUUID.objects.all().delete()
        with CaptureQueriesContext(connection) as old_ctx:
            recompute_role_evaluations(ObjectRole.objects.iterator(), types_prefetch=types_prefetch)
        old_evals = RoleEvaluation.objects.count()

        RoleEvaluation.objects.all().delete()
        RoleEvaluationUUID.objects.all().delete()
        with CaptureQueriesContext(connection) as new_ctx:
            recompute_all_role_evaluations()
        new_evals = RoleEvaluation.objects.count()

        assert old_evals == new_evals, "Both approaches must produce the same evaluations"
        assert len(new_ctx) < len(old_ctx), f"Batched prefetch ({len(new_ctx)} queries) should use fewer queries " f"than iterator ({len(old_ctx)} queries)"


class TestUUIDEvaluationPath:
    @pytest.fixture
    def uuid_rd(self):
        return RoleDefinition.objects.create_from_permissions(
            permissions=['view_uuidmodel', 'change_uuidmodel'],
            name='test-uuid-rd',
            content_type=permission_registry.content_type_model.objects.get_for_model(UUIDModel),
        )

    @pytest.fixture
    def org_uuid_rd(self):
        return RoleDefinition.objects.create_from_permissions(
            permissions=['view_organization', 'view_uuidmodel', 'change_uuidmodel'],
            name='test-org-uuid-rd',
            content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
        )

    @pytest.mark.django_db
    def test_uuid_object_role_prefetch(self, uuid_rd, rando):
        """EvaluationsPrefetch correctly loads UUID-keyed evaluations for a direct assignment."""
        org = Organization.objects.create(name='uuid_test_org')
        uuid_obj = UUIDModel.objects.create(organization=org)
        assignment = uuid_rd.give_permission(rando, uuid_obj)

        role = assignment.object_role
        ep = EvaluationsPrefetch.from_roles([role])

        uuid_partials = ep.get_partials_uuid(role.pk)
        assert len(uuid_partials) > 0, "UUID evaluations should be loaded"
        for codename, ct_id, obj_id in uuid_partials:
            assert obj_id == uuid_obj.pk

    @pytest.mark.django_db
    def test_uuid_recompute_round_trip(self, uuid_rd, rando):
        """Deleting and recomputing UUID evaluations produces identical results."""
        org = Organization.objects.create(name='uuid_rt_org')
        uuid_obj = UUIDModel.objects.create(organization=org)
        uuid_rd.give_permission(rando, uuid_obj)

        original = set(RoleEvaluationUUID.objects.values_list('codename', 'content_type_id', 'object_id', 'role_id'))
        assert len(original) > 0

        RoleEvaluationUUID.objects.all().delete()
        recompute_all_role_evaluations()

        recomputed = set(RoleEvaluationUUID.objects.values_list('codename', 'content_type_id', 'object_id', 'role_id'))
        assert recomputed == original

    @pytest.mark.django_db
    def test_org_scoped_uuid_evaluations(self, org_uuid_rd, rando):
        """Org-scoped role with UUID child permissions produces both int and UUID evaluations."""
        org = Organization.objects.create(name='uuid_org_scope')
        uuid_obj = UUIDModel.objects.create(organization=org)
        org_uuid_rd.give_permission(rando, org)

        role = ObjectRole.objects.get(object_id=str(org.pk), role_definition=org_uuid_rd)
        ep = EvaluationsPrefetch.from_roles([role])

        int_partials = ep.get_partials(role.pk)
        uuid_partials = ep.get_partials_uuid(role.pk)
        assert len(int_partials) > 0, "Should have int evaluations for Organization"
        assert len(uuid_partials) > 0, "Should have UUID evaluations for UUIDModel child"

        uuid_obj_ids = {obj_id for _, _, obj_id in uuid_partials}
        assert uuid_obj.pk in uuid_obj_ids

    @pytest.mark.django_db
    def test_uuid_prefetch_matches_fallback(self, uuid_rd, rando):
        """Prefetch and fallback paths produce identical results for UUID models."""
        org = Organization.objects.create(name='uuid_match_org')
        uuid_obj = UUIDModel.objects.create(organization=org)
        assignment = uuid_rd.give_permission(rando, uuid_obj)

        types_prefetch = TypesPrefetch.from_db()
        role = assignment.object_role

        to_delete_fallback, to_add_fallback = role.needed_cache_updates(types_prefetch=types_prefetch)

        ep = EvaluationsPrefetch.from_roles([role])
        to_delete_ep, to_add_ep = role.needed_cache_updates(types_prefetch=types_prefetch, evaluations_prefetch=ep)

        assert to_delete_fallback == to_delete_ep
        assert set((e.codename, e.content_type_id, e.object_id) for e in to_add_fallback) == set(
            (e.codename, e.content_type_id, e.object_id) for e in to_add_ep
        )


class TestChunkBoundary:
    @pytest.mark.django_db
    def test_chunk_boundary_no_roles_skipped_or_duplicated(self, org_inv_rd, rando):
        """Keyset pagination at chunk boundaries doesn't skip or double-process roles."""
        orgs = [Organization.objects.create(name=f'chunk_org_{i}') for i in range(5)]
        for org in orgs:
            Inventory.objects.create(name=f'chunk_inv_{org.name}', organization=org)
            org_inv_rd.give_permission(rando, org)

        original_int = set(RoleEvaluation.objects.values_list('codename', 'content_type_id', 'object_id', 'role_id'))
        original_uuid = set(RoleEvaluationUUID.objects.values_list('codename', 'content_type_id', 'object_id', 'role_id'))
        n_roles = ObjectRole.objects.count()
        assert n_roles >= 5

        RoleEvaluation.objects.all().delete()
        RoleEvaluationUUID.objects.all().delete()

        with mock.patch('ansible_base.rbac.caching.RECOMPUTE_CHUNK_SIZE', 2):
            with mock.patch.object(EvaluationsPrefetch, 'from_roles', wraps=EvaluationsPrefetch.from_roles) as mock_from_roles:
                recompute_all_role_evaluations()

        assert mock_from_roles.call_count >= 3, f"Expected >=3 chunks for {n_roles} roles at chunk_size=2, got {mock_from_roles.call_count}"

        recomputed_int = set(RoleEvaluation.objects.values_list('codename', 'content_type_id', 'object_id', 'role_id'))
        recomputed_uuid = set(RoleEvaluationUUID.objects.values_list('codename', 'content_type_id', 'object_id', 'role_id'))
        assert recomputed_int == original_int, "Chunk boundary must not skip or duplicate int evaluations"
        assert recomputed_uuid == original_uuid, "Chunk boundary must not skip or duplicate UUID evaluations"

    @pytest.mark.django_db
    def test_chunk_size_one_still_correct(self, org_inv_rd, rando):
        """Degenerate chunk size of 1 (every role in its own chunk) still produces correct results."""
        org = Organization.objects.create(name='chunk1_org')
        Inventory.objects.create(name='chunk1_inv', organization=org)
        org_inv_rd.give_permission(rando, org)

        original = set(RoleEvaluation.objects.values_list('codename', 'content_type_id', 'object_id', 'role_id'))
        assert len(original) > 0

        RoleEvaluation.objects.all().delete()
        RoleEvaluationUUID.objects.all().delete()

        with mock.patch('ansible_base.rbac.caching.RECOMPUTE_CHUNK_SIZE', 1):
            recompute_all_role_evaluations()

        recomputed = set(RoleEvaluation.objects.values_list('codename', 'content_type_id', 'object_id', 'role_id'))
        assert recomputed == original

    @pytest.mark.django_db
    def test_exact_chunk_boundary_roles_equal_chunk_size(self, org_inv_rd, rando):
        """When role count == chunk size, one full chunk is processed and the next iteration exits cleanly."""
        orgs = [Organization.objects.create(name=f'exact_org_{i}') for i in range(3)]
        for org in orgs:
            Inventory.objects.create(name=f'exact_inv_{org.name}', organization=org)
            org_inv_rd.give_permission(rando, org)

        n_roles = ObjectRole.objects.count()

        original_int = set(RoleEvaluation.objects.values_list('codename', 'content_type_id', 'object_id', 'role_id'))
        original_uuid = set(RoleEvaluationUUID.objects.values_list('codename', 'content_type_id', 'object_id', 'role_id'))
        assert len(original_int) > 0

        RoleEvaluation.objects.all().delete()
        RoleEvaluationUUID.objects.all().delete()

        with mock.patch('ansible_base.rbac.caching.RECOMPUTE_CHUNK_SIZE', n_roles):
            with mock.patch.object(EvaluationsPrefetch, 'from_roles', wraps=EvaluationsPrefetch.from_roles) as mock_from_roles:
                recompute_all_role_evaluations()

        assert mock_from_roles.call_count == 1, f"Exactly {n_roles} roles at chunk_size={n_roles} should produce 1 chunk call, got {mock_from_roles.call_count}"

        recomputed_int = set(RoleEvaluation.objects.values_list('codename', 'content_type_id', 'object_id', 'role_id'))
        recomputed_uuid = set(RoleEvaluationUUID.objects.values_list('codename', 'content_type_id', 'object_id', 'role_id'))
        assert recomputed_int == original_int
        assert recomputed_uuid == original_uuid

    @pytest.mark.django_db
    def test_chunk_boundary_one_over(self, org_inv_rd, rando):
        """When role count == chunk_size + 1, the last role spills into a second chunk."""
        orgs = [Organization.objects.create(name=f'over_org_{i}') for i in range(3)]
        for org in orgs:
            Inventory.objects.create(name=f'over_inv_{org.name}', organization=org)
            org_inv_rd.give_permission(rando, org)

        n_roles = ObjectRole.objects.count()
        assert n_roles >= 3

        original_int = set(RoleEvaluation.objects.values_list('codename', 'content_type_id', 'object_id', 'role_id'))
        assert len(original_int) > 0

        RoleEvaluation.objects.all().delete()
        RoleEvaluationUUID.objects.all().delete()

        with mock.patch('ansible_base.rbac.caching.RECOMPUTE_CHUNK_SIZE', n_roles - 1):
            with mock.patch.object(EvaluationsPrefetch, 'from_roles', wraps=EvaluationsPrefetch.from_roles) as mock_from_roles:
                recompute_all_role_evaluations()

        assert mock_from_roles.call_count == 2, f"{n_roles} roles at chunk_size={n_roles - 1} should produce 2 chunk calls, got {mock_from_roles.call_count}"

        recomputed_int = set(RoleEvaluation.objects.values_list('codename', 'content_type_id', 'object_id', 'role_id'))
        assert recomputed_int == original_int


class TestMixedPKRecomputeEndToEnd:
    """Verify chunked recompute handles a mix of int-PK and UUID-PK ObjectRoles in the same batch."""

    @pytest.fixture
    def org_uuid_rd(self):
        return RoleDefinition.objects.create_from_permissions(
            permissions=['view_organization', 'view_uuidmodel', 'change_uuidmodel'],
            name='test-mixed-org-uuid-rd',
            content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
        )

    @pytest.mark.django_db
    def test_mixed_int_uuid_recompute(self, org_inv_rd, org_uuid_rd, rando):
        """recompute_all_role_evaluations correctly rebuilds both int and UUID evaluations
        when ObjectRoles for int-PK and UUID-PK models coexist in the same chunk."""
        org1 = Organization.objects.create(name='mixed_int_org')
        Inventory.objects.create(name='mixed_inv', organization=org1)
        org_inv_rd.give_permission(rando, org1)

        org2 = Organization.objects.create(name='mixed_uuid_org')
        UUIDModel.objects.create(organization=org2)
        UUIDModel.objects.create(organization=org2)
        org_uuid_rd.give_permission(rando, org2)

        original_int = set(RoleEvaluation.objects.values_list('codename', 'content_type_id', 'object_id', 'role_id'))
        original_uuid = set(RoleEvaluationUUID.objects.values_list('codename', 'content_type_id', 'object_id', 'role_id'))
        assert len(original_int) > 0, "Should have int evaluations from Inventory and Organization"
        assert len(original_uuid) > 0, "Should have UUID evaluations from UUIDModel"

        RoleEvaluation.objects.all().delete()
        RoleEvaluationUUID.objects.all().delete()

        recompute_all_role_evaluations()

        recomputed_int = set(RoleEvaluation.objects.values_list('codename', 'content_type_id', 'object_id', 'role_id'))
        recomputed_uuid = set(RoleEvaluationUUID.objects.values_list('codename', 'content_type_id', 'object_id', 'role_id'))
        assert recomputed_int == original_int, "Int evaluations should be identical after mixed recompute"
        assert recomputed_uuid == original_uuid, "UUID evaluations should be identical after mixed recompute"

    @pytest.mark.django_db
    def test_mixed_int_uuid_chunked_across_boundary(self, org_inv_rd, org_uuid_rd, rando):
        """When int-PK and UUID-PK ObjectRoles land in different chunks, EvaluationUpdates
        correctly accumulates and applies both types across chunk boundaries."""
        org1 = Organization.objects.create(name='cross_int_org')
        Inventory.objects.create(name='cross_inv', organization=org1)
        org_inv_rd.give_permission(rando, org1)

        org2 = Organization.objects.create(name='cross_uuid_org')
        UUIDModel.objects.create(organization=org2)
        org_uuid_rd.give_permission(rando, org2)

        original_int = set(RoleEvaluation.objects.values_list('codename', 'content_type_id', 'object_id', 'role_id'))
        original_uuid = set(RoleEvaluationUUID.objects.values_list('codename', 'content_type_id', 'object_id', 'role_id'))
        assert len(original_int) > 0
        assert len(original_uuid) > 0

        RoleEvaluation.objects.all().delete()
        RoleEvaluationUUID.objects.all().delete()

        with mock.patch('ansible_base.rbac.caching.RECOMPUTE_CHUNK_SIZE', 1):
            recompute_all_role_evaluations()

        recomputed_int = set(RoleEvaluation.objects.values_list('codename', 'content_type_id', 'object_id', 'role_id'))
        recomputed_uuid = set(RoleEvaluationUUID.objects.values_list('codename', 'content_type_id', 'object_id', 'role_id'))
        assert recomputed_int == original_int, "Int evaluations must survive cross-chunk accumulation"
        assert recomputed_uuid == original_uuid, "UUID evaluations must survive cross-chunk accumulation"
