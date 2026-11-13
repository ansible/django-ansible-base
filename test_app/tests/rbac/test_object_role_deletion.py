"""Live regression tests for ObjectRole deletion across vendors.

On SQL Server Django cannot defer constraint checks, so its deletion collector
NULLs nullable cascading foreign keys before deleting. Nulling
RoleUserAssignment.object_role turns object-scoped grants into global grants,
and two grants with the same (actor, role_definition) collide on the
unique_global_*_assignment partial unique index. Deleting the assignment rows
first avoids that.
"""

from unittest.mock import Mock

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


@pytest.mark.django_db
class TestRoleDefinitionDeletion:
    def test_deleting_role_definition_removes_multi_object_assignments(self, rando, organization, inv_rd):
        """Deleting a RoleDefinition cascades into its ObjectRoles through Django's
        deletion collector. On SQL Server the collector NULLs the nullable
        assignment.object_role foreign key before deleting, and two object-scoped
        grants for one actor then violate unique_global_user_assignment — the same
        collision delete_object_roles exists to prevent, reached through the
        collector instead of the explicit cleanup paths."""
        from test_app.models import Inventory

        inventory_a = Inventory.objects.create(name='rd-delete-inv-a', organization=organization)
        inventory_b = Inventory.objects.create(name='rd-delete-inv-b', organization=organization)
        inv_rd.give_permission(rando, inventory_a)
        inv_rd.give_permission(rando, inventory_b)

        assert RoleUserAssignment.objects.filter(role_definition=inv_rd, user=rando).count() == 2

        inv_rd.delete()

        assert not ObjectRole.objects.filter(role_definition_id=inv_rd.id).exists()
        assert not RoleUserAssignment.objects.filter(role_definition_id=inv_rd.id).exists()

    def test_deleting_role_definition_queryset_removes_multi_object_assignments(self, rando, organization, inv_rd):
        """QuerySet.delete() bypasses Model.delete(), so the queryset form needs
        its own route through the same mssql-safe object-role cleanup as the
        instance method."""
        from test_app.models import Inventory

        inventory_a = Inventory.objects.create(name='rd-qs-delete-inv-a', organization=organization)
        inventory_b = Inventory.objects.create(name='rd-qs-delete-inv-b', organization=organization)
        inv_rd.give_permission(rando, inventory_a)
        inv_rd.give_permission(rando, inventory_b)

        assert RoleUserAssignment.objects.filter(role_definition=inv_rd, user=rando).count() == 2

        RoleDefinition.objects.filter(pk=inv_rd.pk).delete()

        assert not RoleDefinition.objects.filter(pk=inv_rd.pk).exists()
        assert not ObjectRole.objects.filter(role_definition_id=inv_rd.id).exists()
        assert not RoleUserAssignment.objects.filter(role_definition_id=inv_rd.id).exists()

    def test_deleting_role_definition_queryset_with_relation_filter_removes_it(self, rando, organization, inv_rd):
        """The mssql cleanup deletes the object roles before the queryset delete
        re-evaluates the filter, so a filter that spans that relation
        (object_roles__users=...) stops matching and the role definition would be
        retained while its grants are removed — the deletion targets must be
        frozen before cleanup."""
        from test_app.models import Inventory

        inventory_a = Inventory.objects.create(name='rd-rel-delete-inv-a', organization=organization)
        inventory_b = Inventory.objects.create(name='rd-rel-delete-inv-b', organization=organization)
        inv_rd.give_permission(rando, inventory_a)
        inv_rd.give_permission(rando, inventory_b)

        RoleDefinition.objects.filter(object_roles__users=rando, pk=inv_rd.pk).delete()

        assert not RoleDefinition.objects.filter(pk=inv_rd.pk).exists()
        assert not ObjectRole.objects.filter(role_definition_id=inv_rd.id).exists()
        assert not RoleUserAssignment.objects.filter(role_definition_id=inv_rd.id).exists()

    @pytest.mark.django_db(transaction=True)
    def test_deleting_role_definition_is_atomic(self, rando, organization, inv_rd, monkeypatch):
        """A failure in the collector after the object-role cleanup must roll
        the cleanup back with it: a failed role-definition delete leaves the
        grants in place, on every vendor (in autocommit the cleanup otherwise
        commits before the collector runs)."""
        from test_app.models import Inventory

        def collector_failure(self, *args, **kwargs):
            raise RuntimeError('simulated collector failure')

        inventory_a = Inventory.objects.create(name='rd-atomic-inv-a', organization=organization)
        inventory_b = Inventory.objects.create(name='rd-atomic-inv-b', organization=organization)
        inv_rd.give_permission(rando, inventory_a)
        inv_rd.give_permission(rando, inventory_b)
        assert RoleUserAssignment.objects.filter(role_definition=inv_rd, user=rando).count() == 2

        monkeypatch.setattr('django.db.models.Model.delete', collector_failure)

        with pytest.raises(RuntimeError, match='simulated collector failure'):
            inv_rd.delete()

        inv_rd.refresh_from_db()
        assert ObjectRole.objects.filter(role_definition_id=inv_rd.id).count() == 2
        assert RoleUserAssignment.objects.filter(role_definition=inv_rd, user=rando).count() == 2


def test_role_definition_queryset_delete_routes_cleanup_to_write_database(monkeypatch):
    """QuerySet.db resolves through the router's read alias unless _for_write is
    set (Django's own QuerySet.delete sets it before reading .db), so the mssql
    cleanup must run on the same write database as the deletion itself — not on
    a read replica."""
    import types

    from django.db import router
    from django.db.models import QuerySet

    import ansible_base.rbac.models.role as role_module

    class ReadReplicaRouter:
        def db_for_read(self, model, **hints):
            return 'replica'

        def db_for_write(self, model, **hints):
            return 'default'

    class FakeConnection:
        def __init__(self, vendor):
            self.vendor = vendor

    class FakeAtomic:
        def __init__(self, using):
            FakeAtomic.using = using

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    cleanup_dbs = []

    def fake_delete_object_roles(queryset):
        cleanup_dbs.append(queryset.db)

    super_delete = Mock()

    monkeypatch.setattr(role_module, 'connections', {'default': FakeConnection('microsoft'), 'replica': FakeConnection('postgresql')})
    monkeypatch.setattr(role_module, 'transaction', types.SimpleNamespace(atomic=FakeAtomic))
    monkeypatch.setattr(router, 'routers', [ReadReplicaRouter()])
    monkeypatch.setattr('ansible_base.rbac.caching.delete_object_roles', fake_delete_object_roles)
    monkeypatch.setattr(QuerySet, 'delete', super_delete)
    # the freeze step evaluates the queryset before the (patched) delete
    super_delete.return_value = (0, {})
    queryset = RoleDefinition.objects.all()
    queryset.values_list = Mock(return_value=iter([1]))

    queryset.delete()

    assert cleanup_dbs == ['default']
    super_delete.assert_called_once()


@pytest.mark.django_db
class TestContentTypeDeletion:
    def test_deleting_content_type_removes_multi_object_assignments(self, rando, organization, inv_rd):
        """Deleting a DABContentType cascades into both the RoleDefinitions typed
        by it and the ObjectRoles anchored on it, and through those into the
        assignments. On SQL Server the collector NULLs the nullable
        assignment.object_role foreign key first, and two object-scoped grants
        for one actor then violate unique_global_user_assignment — the same
        collision delete_object_roles exists to prevent, reached through the
        content-type cascade."""
        from ansible_base.rbac.models import DABContentType
        from test_app.models import Inventory

        inventory_a = Inventory.objects.create(name='ct-delete-inv-a', organization=organization)
        inventory_b = Inventory.objects.create(name='ct-delete-inv-b', organization=organization)
        inv_rd.give_permission(rando, inventory_a)
        inv_rd.give_permission(rando, inventory_b)

        assert RoleUserAssignment.objects.filter(role_definition=inv_rd, user=rando).count() == 2

        ct = DABContentType.objects.get_for_model(Inventory)
        ct.delete()

        assert not DABContentType.objects.filter(pk=ct.pk).exists()
        assert not ObjectRole.objects.filter(content_type_id=ct.id).exists()
        assert not RoleUserAssignment.objects.filter(role_definition_id=inv_rd.id).exists()

    def test_deleting_content_type_queryset_removes_multi_object_assignments(self, rando, organization, inv_rd):
        """QuerySet.delete() bypasses Model.delete(), so the queryset form needs
        its own route through the same mssql-safe object-role cleanup as the
        instance method."""
        from ansible_base.rbac.models import DABContentType
        from test_app.models import Inventory

        inventory_a = Inventory.objects.create(name='ct-qs-delete-inv-a', organization=organization)
        inventory_b = Inventory.objects.create(name='ct-qs-delete-inv-b', organization=organization)
        inv_rd.give_permission(rando, inventory_a)
        inv_rd.give_permission(rando, inventory_b)

        assert RoleUserAssignment.objects.filter(role_definition=inv_rd, user=rando).count() == 2

        ct = DABContentType.objects.get_for_model(Inventory)
        DABContentType.objects.filter(objectrole__role_definition=inv_rd, pk=ct.pk).delete()

        assert not DABContentType.objects.filter(pk=ct.pk).exists()
        assert not ObjectRole.objects.filter(content_type_id=ct.id).exists()
        assert not RoleUserAssignment.objects.filter(role_definition_id=inv_rd.id).exists()


def test_delete_object_roles_routes_to_write_database(monkeypatch):
    """delete_object_roles resolves its database from queryset.db, which routes
    through the router's read alias unless _for_write is set — the helper must
    run its transaction on the same write database as the deletion itself."""
    import types

    from django.db import router

    import ansible_base.rbac.caching as caching_module

    class ReadReplicaRouter:
        def db_for_read(self, model, **hints):
            return 'replica'

        def db_for_write(self, model, **hints):
            return 'default'

    class FakeConnection:
        def __init__(self, vendor):
            self.vendor = vendor

    class FakeAtomic:
        def __init__(self, using):
            FakeAtomic.using = using

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(caching_module, 'connections', {'default': FakeConnection('microsoft'), 'replica': FakeConnection('postgresql')})
    monkeypatch.setattr(caching_module, 'transaction', types.SimpleNamespace(atomic=FakeAtomic))
    monkeypatch.setattr(router, 'routers', [ReadReplicaRouter()])

    queryset = ObjectRole.objects.all()
    # empty candidate set: the helper returns inside its transaction without
    # touching the database, so the alias is the only observable routing fact
    queryset.values_list = Mock(return_value=iter([]))
    queryset.delete = Mock(return_value=(0, {}))

    assert caching_module.delete_object_roles(queryset) == (0, {})
    queryset.delete.assert_not_called()  # the passthrough means it ran on the replica

    assert FakeAtomic.using == 'default'
