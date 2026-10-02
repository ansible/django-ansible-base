from unittest.mock import MagicMock

import pytest
from rest_framework.exceptions import ValidationError

from ansible_base.rbac.models import RoleUserAssignment
from ansible_base.rbac.pipeline import bulk_give_permissions, bulk_remove_permissions
from ansible_base.rbac.triggers import dab_rbac_assignments_created, dab_rbac_assignments_pre_delete
from test_app.models import Inventory, User


@pytest.mark.django_db
class TestBulkAssignmentCreatedSignal:
    """Tests for dab_rbac_assignments_created signal."""

    def test_bulk_give_fires_created_signal(self, organization, rando, org_inv_rd):
        """bulk_give_permissions with 2+ user triples should fire signal once with all assignments."""
        second_user = User.objects.create(username='signal-user-2')
        mck = MagicMock()
        dab_rbac_assignments_created.connect(mck.signal_handler, dispatch_uid='test-created')

        try:
            assignments = bulk_give_permissions(
                user_permissions=[
                    (org_inv_rd, rando, organization),
                    (org_inv_rd, second_user, organization),
                ]
            )

            mck.signal_handler.assert_called_once()
            call_kwargs = mck.signal_handler.call_args.kwargs
            assert 'assignments' in call_kwargs
            assert 'content_objects' in call_kwargs
            assert len(call_kwargs['assignments']) == 2
            assert all(a in call_kwargs['assignments'] for a in assignments)
            # Verify content_objects dict contains the organization
            for assignment in call_kwargs['assignments']:
                key = (assignment.content_type_id, assignment.object_id)
                assert key in call_kwargs['content_objects']
                assert call_kwargs['content_objects'][key] == organization
        finally:
            dab_rbac_assignments_created.disconnect(mck.signal_handler, dispatch_uid='test-created')

    def test_single_give_permission_fires_created_signal(self, organization, rando, org_inv_rd):
        """RoleDefinition.give_permission() should fire signal with a 1-element list."""
        mck = MagicMock()
        dab_rbac_assignments_created.connect(mck.signal_handler, dispatch_uid='test-single')

        try:
            assignment = org_inv_rd.give_permission(rando, organization)

            mck.signal_handler.assert_called_once()
            call_kwargs = mck.signal_handler.call_args.kwargs
            assert 'assignments' in call_kwargs
            assert 'content_objects' in call_kwargs
            assert len(call_kwargs['assignments']) == 1
            assert call_kwargs['assignments'][0] == assignment
            # Content object should be present (give_permission calls bulk_give_permissions)
            key = (assignment.content_type_id, assignment.object_id)
            assert key in call_kwargs['content_objects']
            assert call_kwargs['content_objects'][key] == organization
        finally:
            dab_rbac_assignments_created.disconnect(mck.signal_handler, dispatch_uid='test-single')

    def test_bulk_give_idempotent_no_signal(self, organization, rando, org_inv_rd):
        """Giving the same permissions twice should not fire signal on the second call."""
        # First call creates the assignment
        bulk_give_permissions(user_permissions=[(org_inv_rd, rando, organization)])

        # Second call should be idempotent (no new assignments created)
        mck = MagicMock()
        dab_rbac_assignments_created.connect(mck.signal_handler, dispatch_uid='test-idempotent')

        try:
            assignments = bulk_give_permissions(user_permissions=[(org_inv_rd, rando, organization)])

            # Signal should not fire if no new assignments were created
            if not assignments or all(a.pk is None for a in assignments):
                mck.signal_handler.assert_not_called()
        finally:
            dab_rbac_assignments_created.disconnect(mck.signal_handler, dispatch_uid='test-idempotent')

    def test_bulk_give_team_fires_created_signal(self, organization, team, inv_rd):
        """bulk_give_permissions with team triples should include team assignments in signal."""
        inv = Inventory.objects.create(name='signal-inv', organization=organization)
        mck = MagicMock()
        dab_rbac_assignments_created.connect(mck.signal_handler, dispatch_uid='test-team')

        try:
            assignments = bulk_give_permissions(team_permissions=[(inv_rd, team, inv)])

            mck.signal_handler.assert_called_once()
            call_kwargs = mck.signal_handler.call_args.kwargs
            assert 'assignments' in call_kwargs
            assert 'content_objects' in call_kwargs
            assert len(call_kwargs['assignments']) == 1
            assignment = call_kwargs['assignments'][0]
            assert assignment == assignments[0]
            assert assignment.team == team
            # Verify content object in dict
            key = (assignment.content_type_id, assignment.object_id)
            assert call_kwargs['content_objects'][key] == inv
        finally:
            dab_rbac_assignments_created.disconnect(mck.signal_handler, dispatch_uid='test-team')

    def test_bulk_give_mixed_fires_created_signal(self, organization, team, rando, inv_rd):
        """Mix of user and team triples should all appear in one signal."""
        inv = Inventory.objects.create(name='mixed-inv', organization=organization)
        mck = MagicMock()
        dab_rbac_assignments_created.connect(mck.signal_handler, dispatch_uid='test-mixed')

        try:
            assignments = bulk_give_permissions(
                user_permissions=[(inv_rd, rando, inv)],
                team_permissions=[(inv_rd, team, inv)],
            )

            mck.signal_handler.assert_called_once()
            call_kwargs = mck.signal_handler.call_args.kwargs
            assert 'assignments' in call_kwargs
            assert 'content_objects' in call_kwargs
            assert len(call_kwargs['assignments']) == 2
            assert all(a in call_kwargs['assignments'] for a in assignments)
            # Verify all assignments have content objects in dict
            for assignment in call_kwargs['assignments']:
                key = (assignment.content_type_id, assignment.object_id)
                assert call_kwargs['content_objects'][key] == inv
        finally:
            dab_rbac_assignments_created.disconnect(mck.signal_handler, dispatch_uid='test-mixed')

    def test_created_signal_fires_once_with_new_rows(self, organization, rando, org_inv_rd):
        """The bulk created signal fires once per operation with the newly-created rows.

        The fire_signals_on_create toggle is gone. (DAB also temporarily re-fires per-row
        post_save during the AAP-90162 merge window so not-yet-migrated consumers keep
        working — that is orthogonal to this signal, which is the migration target.)
        """
        mck = MagicMock()
        dab_rbac_assignments_created.connect(mck.signal_handler, dispatch_uid='test-only-hook')

        try:
            assignments = bulk_give_permissions(
                user_permissions=[(org_inv_rd, rando, organization)],
            )

            mck.signal_handler.assert_called_once()
            call_kwargs = mck.signal_handler.call_args.kwargs
            assert 'assignments' in call_kwargs
            assert 'content_objects' in call_kwargs
            assert len(call_kwargs['assignments']) == 1
            assert call_kwargs['assignments'][0] == assignments[0]
        finally:
            dab_rbac_assignments_created.disconnect(mck.signal_handler, dispatch_uid='test-only-hook')

    def test_created_signal_fires_after_recompute(self, inventory, rando, inv_rd):
        """The created signal fires *after* recomputation: RoleEvaluation is already settled.

        A handler that queries effective permissions inline sees accurate results -- this is
        the documented contract (see docs/apps/rbac/bulk_operations.md). Before the signal was
        moved below recompute, has_obj_perm would have been stale (False) at this point.
        """
        seen = {}

        def handler(sender, assignments, content_objects, **kwargs):
            seen['has_perm'] = rando.has_obj_perm(inventory, 'change_inventory')

        dab_rbac_assignments_created.connect(handler, dispatch_uid='test-created-ordering')
        try:
            bulk_give_permissions(user_permissions=[(inv_rd, rando, inventory)])
            assert seen['has_perm'] is True
        finally:
            dab_rbac_assignments_created.disconnect(handler, dispatch_uid='test-created-ordering')


@pytest.mark.django_db
class TestGlobalAssignmentSignals:
    """Global (singleton) role assignments must fire the same bulk signals (AAP-90170)."""

    def test_give_global_user_fires_created_signal(self, rando, global_inv_rd):
        mck = MagicMock()
        dab_rbac_assignments_created.connect(mck.signal_handler, dispatch_uid='test-global-user')
        try:
            assignment = global_inv_rd.give_global_permission(rando)

            mck.signal_handler.assert_called_once()
            call_kwargs = mck.signal_handler.call_args.kwargs
            assert call_kwargs['assignments'] == [assignment]
            # Global assignments carry no content object
            assert assignment.object_role is None
            assert assignment.content_type_id is None
            assert assignment.object_id is None
            assert call_kwargs['content_objects'] == {}
        finally:
            dab_rbac_assignments_created.disconnect(mck.signal_handler, dispatch_uid='test-global-user')

    def test_give_global_team_fires_created_signal(self, team, global_inv_rd):
        mck = MagicMock()
        dab_rbac_assignments_created.connect(mck.signal_handler, dispatch_uid='test-global-team')
        try:
            assignment = global_inv_rd.give_global_permission(team)

            mck.signal_handler.assert_called_once()
            call_kwargs = mck.signal_handler.call_args.kwargs
            assert call_kwargs['assignments'] == [assignment]
            assert assignment.team == team
            assert assignment.object_role is None
        finally:
            dab_rbac_assignments_created.disconnect(mck.signal_handler, dispatch_uid='test-global-team')

    def test_give_global_idempotent_no_signal(self, rando, global_inv_rd):
        """Re-granting an existing global role must not fire the created signal."""
        global_inv_rd.give_global_permission(rando)

        mck = MagicMock()
        dab_rbac_assignments_created.connect(mck.signal_handler, dispatch_uid='test-global-idem')
        try:
            # Idempotent re-grant returns the existing assignment but creates nothing
            assignment = global_inv_rd.give_global_permission(rando)
            assert assignment is not None
            mck.signal_handler.assert_not_called()
        finally:
            dab_rbac_assignments_created.disconnect(mck.signal_handler, dispatch_uid='test-global-idem')

    def test_remove_global_user_fires_pre_delete_signal(self, rando, global_inv_rd):
        global_inv_rd.give_global_permission(rando)

        captured = {}

        def capture(sender, assignments, content_objects, **kwargs):
            captured['assignments'] = list(assignments)
            captured['user_id'] = assignments[0].user_id
            captured['object_role'] = assignments[0].object_role

        dab_rbac_assignments_pre_delete.connect(capture, dispatch_uid='test-global-rm')
        try:
            global_inv_rd.remove_global_permission(rando)

            assert captured['user_id'] == rando.pk
            assert captured['object_role'] is None
            assert len(captured['assignments']) == 1
        finally:
            dab_rbac_assignments_pre_delete.disconnect(capture, dispatch_uid='test-global-rm')

    def test_remove_global_team_fires_pre_delete_signal(self, team, global_inv_rd):
        global_inv_rd.give_global_permission(team)

        mck = MagicMock()
        dab_rbac_assignments_pre_delete.connect(mck.signal_handler, dispatch_uid='test-global-team-rm')
        try:
            global_inv_rd.remove_global_permission(team)

            mck.signal_handler.assert_called_once()
            assert mck.signal_handler.call_args.kwargs['assignments'][0].team == team
        finally:
            dab_rbac_assignments_pre_delete.disconnect(mck.signal_handler, dispatch_uid='test-global-team-rm')

    def test_give_global_returns_identity_preserving_assignment(self, rando, team, global_inv_rd):
        """give_global_permission must return an assignment whose role_definition/actor are
        the exact objects passed in (the old get_or_create path did; downstream relies on
        `assignment.role_definition is rd`). AAP-90170."""
        user_assignment = global_inv_rd.give_global_permission(rando)
        assert user_assignment.role_definition is global_inv_rd
        assert user_assignment.user is rando
        assert user_assignment.content_type is None

        team_assignment = global_inv_rd.give_global_permission(team)
        assert team_assignment.role_definition is global_inv_rd
        assert team_assignment.team is team

        # Idempotent re-give (already exists) must also preserve identity
        again = global_inv_rd.give_global_permission(rando)
        assert again.role_definition is global_inv_rd
        assert again.user is rando

    def test_remove_global_nonexistent_no_signal(self, rando, global_inv_rd):
        mck = MagicMock()
        dab_rbac_assignments_pre_delete.connect(mck.signal_handler, dispatch_uid='test-global-noop-rm')
        try:
            global_inv_rd.remove_global_permission(rando)
            mck.signal_handler.assert_not_called()
        finally:
            dab_rbac_assignments_pre_delete.disconnect(mck.signal_handler, dispatch_uid='test-global-noop-rm')

    def test_pipeline_enforces_gates_for_list_callers(self, rando, global_inv_rd, inv_rd, settings):
        """The enablement/content-type gates must be enforced in the pipeline, not just the
        per-actor model method -- a bulk caller passing a list of global triples (content
        object None) must not bypass them. AAP-90170 (validate_global_assignment)."""
        second_user = User.objects.create(username='global-gate-user-2')

        # content_type gate: inv_rd is object-scoped, cannot be assigned globally
        with pytest.raises(ValidationError, match='content type must be null'):
            bulk_give_permissions(user_permissions=[(inv_rd, rando, None)])

        # user-enablement gate applies to every actor in the list, not just the first
        settings.ANSIBLE_BASE_ALLOW_SINGLETON_USER_ROLES = False
        with pytest.raises(ValidationError, match='not enabled for users'):
            bulk_give_permissions(user_permissions=[(global_inv_rd, rando, None), (global_inv_rd, second_user, None)])

    def test_pipeline_validates_every_actor_not_just_first(self, organization, rando, inv_rd):
        """The actor-type check must run for every actor, even when object triples share the same
        (role_definition, content_type). A bad (non-user/team) actor riding behind a valid one
        must still be rejected -- the (rd, content_type) dedup applies only to the rd<->object
        check, never to the per-actor check."""
        inv1 = Inventory.objects.create(name='actor-gate-inv-1', organization=organization)
        inv2 = Inventory.objects.create(name='actor-gate-inv-2', organization=organization)

        with pytest.raises(ValidationError, match='must be a user or team'):
            bulk_give_permissions(
                user_permissions=[
                    (inv_rd, rando, inv1),  # valid -- primes the (inv_rd, inventory-ct) dedup key
                    (inv_rd, organization, inv2),  # same (rd, ct); organization is not a user/team
                ]
            )

        # nothing was persisted -- validation aborts before any creation
        assert not RoleUserAssignment.objects.filter(role_definition=inv_rd).exists()

    def test_bulk_mixes_global_and_object_triples(self, organization, rando, global_inv_rd, org_inv_rd, inv_rd):
        """A single bulk_give/remove call handles global (content object None) and object-scoped
        triples across multiple role definitions in one creation pass -- the unified contract.
        AAP-90170."""
        inv = Inventory.objects.create(name='mixed-global-inv', organization=organization)

        created = bulk_give_permissions(
            user_permissions=[
                (global_inv_rd, rando, None),  # global
                (org_inv_rd, rando, organization),  # object-scoped (organization)
                (inv_rd, rando, inv),  # object-scoped (inventory)
            ]
        )
        assert len(created) == 3
        # exactly one global row (object_role None) and two object rows
        assert len([a for a in created if a.object_role_id is None]) == 1
        assert len([a for a in created if a.object_role_id is not None]) == 2
        # returned rows keep the in-memory role definition (no re-fetch)
        assert any(a.role_definition is global_inv_rd for a in created)
        assert any(a.role_definition is org_inv_rd for a in created)
        assert any(a.role_definition is inv_rd for a in created)

        # Removal mixes the same shapes and clears the global row too
        bulk_remove_permissions(
            user_permissions=[
                (global_inv_rd, rando, None),
                (org_inv_rd, rando, organization),
                (inv_rd, rando, inv),
            ]
        )
        assert not RoleUserAssignment.objects.filter(user=rando, role_definition=global_inv_rd, object_role__isnull=True).exists()
        assert not RoleUserAssignment.objects.filter(user=rando, role_definition=org_inv_rd).exists()
        assert not RoleUserAssignment.objects.filter(user=rando, role_definition=inv_rd).exists()


@pytest.mark.django_db
class TestBulkAssignmentPreDeleteSignal:
    """Tests for dab_rbac_assignments_pre_delete signal."""

    def test_bulk_remove_fires_pre_delete_signal(self, organization, rando, org_inv_rd):
        """bulk_remove_permissions with 2+ triples should fire signal once before deletion."""
        second_user = User.objects.create(username='rm-signal-user-2')
        bulk_give_permissions(
            user_permissions=[
                (org_inv_rd, rando, organization),
                (org_inv_rd, second_user, organization),
            ]
        )

        mck = MagicMock()
        dab_rbac_assignments_pre_delete.connect(mck.signal_handler, dispatch_uid='test-pre-delete')

        try:
            bulk_remove_permissions(
                user_permissions=[
                    (org_inv_rd, rando, organization),
                    (org_inv_rd, second_user, organization),
                ]
            )

            mck.signal_handler.assert_called_once()
            call_kwargs = mck.signal_handler.call_args.kwargs
            assert 'assignments' in call_kwargs
            assert 'content_objects' in call_kwargs
            assert len(call_kwargs['assignments']) == 2
            # Verify content_objects dict contains the organization
            for assignment in call_kwargs['assignments']:
                key = (assignment.content_type_id, assignment.object_id)
                assert call_kwargs['content_objects'][key] == organization
        finally:
            dab_rbac_assignments_pre_delete.disconnect(mck.signal_handler, dispatch_uid='test-pre-delete')

    def test_single_remove_permission_fires_pre_delete_signal(self, organization, rando, org_inv_rd):
        """RoleDefinition.remove_permission() should fire signal."""
        org_inv_rd.give_permission(rando, organization)

        mck = MagicMock()
        dab_rbac_assignments_pre_delete.connect(mck.signal_handler, dispatch_uid='test-single-rm')

        try:
            org_inv_rd.remove_permission(rando, organization)

            mck.signal_handler.assert_called_once()
            call_kwargs = mck.signal_handler.call_args.kwargs
            assert 'assignments' in call_kwargs
            assert 'content_objects' in call_kwargs
            assert len(call_kwargs['assignments']) == 1
        finally:
            dab_rbac_assignments_pre_delete.disconnect(mck.signal_handler, dispatch_uid='test-single-rm')

    def test_pre_delete_signal_has_valid_assignments(self, organization, rando, org_inv_rd):
        """Signal handler should be able to read assignment data before deletion."""
        org_inv_rd.give_permission(rando, organization)

        captured_data = {}

        def capture_assignment_data(sender, assignments, content_objects, **kwargs):
            # Read assignment data — this should not raise because the signal
            # fires BEFORE deletion
            assignment = assignments[0]
            captured_data['role_name'] = assignment.role_definition.name
            captured_data['object_id'] = assignment.object_id
            captured_data['user_id'] = assignment.user_id
            # Look up content object from dict
            key = (assignment.content_type_id, assignment.object_id)
            captured_data['content_object'] = content_objects.get(key)

        dab_rbac_assignments_pre_delete.connect(capture_assignment_data, dispatch_uid='test-valid')

        try:
            bulk_remove_permissions(user_permissions=[(org_inv_rd, rando, organization)])

            assert 'role_name' in captured_data
            assert captured_data['role_name'] == org_inv_rd.name
            assert captured_data['object_id'] == str(organization.pk)
            assert captured_data['user_id'] == rando.pk
            assert captured_data['content_object'] == organization
        finally:
            dab_rbac_assignments_pre_delete.disconnect(capture_assignment_data, dispatch_uid='test-valid')

    def test_pre_delete_signal_fires_before_recompute(self, inventory, rando, inv_rd):
        """The pre_delete signal fires *before* deletion and recomputation.

        At signal time the row still exists and RoleEvaluation still reflects the
        pre-removal state, so has_obj_perm is still True. This is the deliberate counterpart
        to the created signal firing after recompute (see docs/apps/rbac/bulk_operations.md).
        """
        inv_rd.give_permission(rando, inventory)
        seen = {}

        def handler(sender, assignments, content_objects, **kwargs):
            seen['has_perm_at_signal'] = rando.has_obj_perm(inventory, 'change_inventory')

        dab_rbac_assignments_pre_delete.connect(handler, dispatch_uid='test-pre-delete-ordering')
        try:
            bulk_remove_permissions(user_permissions=[(inv_rd, rando, inventory)])
            assert seen['has_perm_at_signal'] is True  # still present before delete/recompute
            assert rando.has_obj_perm(inventory, 'change_inventory') is False  # gone afterward
        finally:
            dab_rbac_assignments_pre_delete.disconnect(handler, dispatch_uid='test-pre-delete-ordering')

    def test_remove_nonexistent_no_signal(self, organization, rando, org_inv_rd):
        """Removing permissions that don't exist should not fire signal."""
        # Don't create the permission first
        mck = MagicMock()
        dab_rbac_assignments_pre_delete.connect(mck.signal_handler, dispatch_uid='test-nonexistent')

        try:
            bulk_remove_permissions(user_permissions=[(org_inv_rd, rando, organization)])

            mck.signal_handler.assert_not_called()
        finally:
            dab_rbac_assignments_pre_delete.disconnect(mck.signal_handler, dispatch_uid='test-nonexistent')

    def test_pre_delete_signal_with_teams(self, organization, team, inv_rd):
        """Signal should fire for team assignment removal."""
        inv = Inventory.objects.create(name='rm-team-inv', organization=organization)
        bulk_give_permissions(team_permissions=[(inv_rd, team, inv)])

        mck = MagicMock()
        dab_rbac_assignments_pre_delete.connect(mck.signal_handler, dispatch_uid='test-team-rm')

        try:
            bulk_remove_permissions(team_permissions=[(inv_rd, team, inv)])

            mck.signal_handler.assert_called_once()
            call_kwargs = mck.signal_handler.call_args.kwargs
            assert 'assignments' in call_kwargs
            assert 'content_objects' in call_kwargs
            assert len(call_kwargs['assignments']) == 1
            assignment = call_kwargs['assignments'][0]
            assert assignment.team == team
            # Verify content object in dict
            key = (assignment.content_type_id, assignment.object_id)
            assert call_kwargs['content_objects'][key] == inv
        finally:
            dab_rbac_assignments_pre_delete.disconnect(mck.signal_handler, dispatch_uid='test-team-rm')

    def test_pre_delete_mixed_assignments(self, organization, team, rando, inv_rd):
        """Mix of user and team removals should all appear in one signal."""
        inv = Inventory.objects.create(name='mixed-rm-inv', organization=organization)
        bulk_give_permissions(
            user_permissions=[(inv_rd, rando, inv)],
            team_permissions=[(inv_rd, team, inv)],
        )

        mck = MagicMock()
        dab_rbac_assignments_pre_delete.connect(mck.signal_handler, dispatch_uid='test-mixed-rm')

        try:
            bulk_remove_permissions(
                user_permissions=[(inv_rd, rando, inv)],
                team_permissions=[(inv_rd, team, inv)],
            )

            mck.signal_handler.assert_called_once()
            call_kwargs = mck.signal_handler.call_args.kwargs
            assert 'assignments' in call_kwargs
            assert 'content_objects' in call_kwargs
            assert len(call_kwargs['assignments']) == 2
            # Verify all assignments have content objects in dict
            for assignment in call_kwargs['assignments']:
                key = (assignment.content_type_id, assignment.object_id)
                assert call_kwargs['content_objects'][key] == inv
        finally:
            dab_rbac_assignments_pre_delete.disconnect(mck.signal_handler, dispatch_uid='test-mixed-rm')
