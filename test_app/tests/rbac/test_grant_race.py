"""Single-assignment grants tolerate the existing row being removed concurrently.

After an idempotent grant the pipeline returns no rows, so give_permission and
give_global_permission fetch the pre-existing row. These tests delete that row between the
no-op insert and the fetch to simulate a concurrent removal.
"""

from functools import partial
from unittest import mock

import pytest

from ansible_base.rbac import pipeline
from ansible_base.rbac.models import RoleUserAssignment

real_bulk_give_permissions = pipeline.bulk_give_permissions


def _remove_existing_after_noop_grants(times):
    """Wrap bulk_give_permissions so its first `times` no-op calls delete the existing row afterwards."""
    calls = []

    def wrapper(*args, **kwargs):
        created = real_bulk_give_permissions(*args, **kwargs)
        calls.append(created)
        if not created and len(calls) <= times:
            for rd, actor, obj in kwargs.get('user_permissions', ()):
                if obj is None:
                    rd.remove_global_permission(actor)
                else:
                    rd.remove_permission(actor, obj)
        return created

    return wrapper, calls


@pytest.mark.django_db
class TestGrantToleratesConcurrentRemoval:
    def test_give_global_permission_regrants_when_existing_row_vanishes(self, rando, global_inv_rd):
        original = global_inv_rd.give_global_permission(rando)
        wrapper, calls = _remove_existing_after_noop_grants(times=1)

        with mock.patch.object(pipeline, 'bulk_give_permissions', wrapper):
            assignment = global_inv_rd.give_global_permission(rando)

        assert [len(created) for created in calls] == [0, 1]
        assert assignment.pk != original.pk
        assert assignment.role_definition is global_inv_rd
        assert assignment.user is rando
        assert RoleUserAssignment.objects.filter(pk=assignment.pk, user=rando, object_role__isnull=True).exists()

    def test_give_permission_regrants_when_existing_row_vanishes(self, rando, inventory, inv_rd):
        original = inv_rd.give_permission(rando, inventory)
        wrapper, calls = _remove_existing_after_noop_grants(times=1)

        with mock.patch.object(pipeline, 'bulk_give_permissions', wrapper):
            assignment = inv_rd.give_permission(rando, inventory)

        assert [len(created) for created in calls] == [0, 1]
        assert assignment.pk != original.pk
        assert RoleUserAssignment.objects.filter(pk=assignment.pk, user=rando, object_id=str(inventory.pk)).exists()
        assert rando.has_obj_perm(inventory, 'change')

    def test_existing_row_is_returned_without_retry(self, rando, inventory, inv_rd, global_inv_rd):
        object_assignment = inv_rd.give_permission(rando, inventory)
        global_assignment = global_inv_rd.give_global_permission(rando)
        wrapper, calls = _remove_existing_after_noop_grants(times=0)

        with mock.patch.object(pipeline, 'bulk_give_permissions', wrapper):
            assert inv_rd.give_permission(rando, inventory).pk == object_assignment.pk
            assert global_inv_rd.give_global_permission(rando).pk == global_assignment.pk

        assert [len(created) for created in calls] == [0, 0]

    @pytest.mark.parametrize('scope', ['object', 'global'])
    def test_raises_when_row_keeps_vanishing(self, rando, inventory, inv_rd, global_inv_rd, scope):
        """A row removed after both attempts is reported, rather than returning None."""
        if scope == 'object':
            grant = partial(inv_rd.give_permission, rando, inventory)
        else:
            grant = partial(global_inv_rd.give_global_permission, rando)
        grant()

        def always_noop_then_remove(*args, **kwargs):
            """Report a no-op every time and remove the row, as if another request keeps deleting it."""
            for rd, actor, obj in kwargs.get('user_permissions', ()):
                RoleUserAssignment.objects.filter(user=actor, role_definition=rd).delete()
            return []

        with mock.patch.object(pipeline, 'bulk_give_permissions', always_noop_then_remove):
            with pytest.raises(RoleUserAssignment.DoesNotExist, match='removed concurrently'):
                grant()
