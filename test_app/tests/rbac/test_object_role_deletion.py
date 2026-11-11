"""Live regression tests for ObjectRole deletion across vendors.

On SQL Server Django cannot defer constraint checks, so its deletion collector
NULLs nullable cascading foreign keys before deleting. Nulling
RoleUserAssignment.object_role turns object-scoped grants into global grants,
and two grants with the same (actor, role_definition) collide on the
unique_global_*_assignment partial unique index. Deleting the assignment rows
first avoids that.
"""

import pytest

from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import ObjectRole, RoleDefinition, RoleTeamAssignment, RoleUserAssignment
from test_app.models import Team


@pytest.mark.django_db
class TestCleanupDeletedObjectRoles:
    def test_object_role_deletion_removes_assignments(self, rando, organization):
        """Deleting ObjectRoles through the cleanup path must remove their
        assignment rows on every vendor, not NULL them into global grants."""
        from ansible_base.rbac.caching import cleanup_deleted_object_roles

        member_rd = RoleDefinition.objects.managed.team_member
        team_a = Team.objects.create(name='cascade-team-a', organization=organization)
        team_b = Team.objects.create(name='cascade-team-b', organization=organization)
        member_rd.give_permission(rando, team_a)
        member_rd.give_permission(rando, team_b)

        team_ct_id = permission_registry.team_ct_id
        object_pks = [(team_ct_id, team_a.pk), (team_ct_id, team_b.pk)]
        expected_role_ids = set(
            ObjectRole.objects.filter(content_type_id=team_ct_id, object_id__in=[str(team_a.pk), str(team_b.pk)]).values_list('id', flat=True)
        )
        assert len(expected_role_ids) == 2

        deleted_or_ids = cleanup_deleted_object_roles(object_pks)

        assert deleted_or_ids == expected_role_ids
        assert not ObjectRole.objects.filter(content_type_id=team_ct_id, object_id__in=[str(team_a.pk), str(team_b.pk)]).exists()
        assert not RoleUserAssignment.objects.filter(object_id__in=[str(team_a.pk), str(team_b.pk)]).exists()

    def test_team_role_cleanup_deletes_object_roles(self, rando, organization):
        """cleanup_deleted_team_roles follows the same ObjectRole deletion path."""
        from ansible_base.rbac.caching import cleanup_deleted_team_roles

        member_rd = RoleDefinition.objects.managed.team_member
        team_a = Team.objects.create(name='cascade-team-c', organization=organization)
        team_b = Team.objects.create(name='cascade-team-d', organization=organization)
        member_rd.give_permission(rando, team_a)
        member_rd.give_permission(rando, team_b)

        team_ct_id = permission_registry.team_ct_id
        expected_role_ids = set(
            ObjectRole.objects.filter(content_type_id=team_ct_id, object_id__in=[str(team_a.pk), str(team_b.pk)]).values_list('id', flat=True)
        )
        assert len(expected_role_ids) == 2

        ancestor_roles, deleted_or_ids = cleanup_deleted_team_roles({team_a.pk, team_b.pk})

        # the member roles grant to the deleted teams via RoleEvaluation, so they are
        # legitimately reported as ancestors for recompute
        assert {role.pk for role in ancestor_roles} == expected_role_ids
        assert deleted_or_ids == expected_role_ids
        assert not ObjectRole.objects.filter(content_type_id=team_ct_id, object_id__in=[str(team_a.pk), str(team_b.pk)]).exists()
        assert not RoleUserAssignment.objects.filter(object_id__in=[str(team_a.pk), str(team_b.pk)]).exists()
        assert not RoleTeamAssignment.objects.filter(object_id__in=[str(team_a.pk), str(team_b.pk)]).exists()


@pytest.mark.django_db
class TestDeleteObjectRolesDirect:
    def test_single_object_role_with_team_assignment(self, team, inv_rd):
        """delete_object_roles removes an ObjectRole with a team assignment attached."""
        from ansible_base.rbac.caching import delete_object_roles
        from test_app.models import Inventory

        inventory = Inventory.objects.create(name='delete-roles-inv', organization=team.organization)
        inv_rd.give_permission(team, inventory)

        queryset = ObjectRole.objects.filter(content_type_id=permission_registry.team_ct_id, object_id=str(team.pk))
        assert not queryset.exists()  # sanity: the object role lives on the inventory, not the team
        object_role = ObjectRole.objects.get(
            role_definition=inv_rd, content_type=permission_registry.content_type_model.objects.get_for_model(Inventory), object_id=str(inventory.pk)
        )

        deleted_count, deleted_by_model = delete_object_roles(ObjectRole.objects.filter(pk=object_role.pk))

        assert deleted_count >= 1
        assert not ObjectRole.objects.filter(pk=object_role.pk).exists()
        assert not RoleTeamAssignment.objects.filter(object_role_id=object_role.pk).exists()
