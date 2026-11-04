"""Tests for pipeline._insert_new and the private Django behavior it relies on.

_insert_new calls the private QuerySet._insert with returning_fields and
on_conflict=OnConflict.IGNORE. The first group of tests pins that Django/database
behavior directly, so a Django upgrade that changes it fails here.
"""

from unittest import mock

import pytest
from django.db import connection
from django.db.models.constants import OnConflict
from django.db.models.query import QuerySet

from ansible_base.rbac.models import RoleDefinition, RoleTeamAssignment, RoleUserAssignment
from ansible_base.rbac.pipeline import _insert_new
from test_app.models import Inventory, User


def _user_assignment(user, rd, obj_role=None):
    return RoleUserAssignment(
        user=user,
        role_definition=rd,
        object_role=obj_role,
        content_type=obj_role.content_type if obj_role else None,
        object_id=obj_role.object_id if obj_role else None,
    )


def _team_assignment(team, rd, obj_role=None):
    return RoleTeamAssignment(
        team=team,
        role_definition=rd,
        object_role=obj_role,
        content_type=obj_role.content_type if obj_role else None,
        object_id=obj_role.object_id if obj_role else None,
    )


@pytest.fixture
def inv_object_role(rando, inventory, inv_rd):
    """An existing object assignment of inv_rd on inventory, held by rando."""
    return inv_rd.give_permission(rando, inventory).object_role


@pytest.fixture
def other_user():
    return User.objects.create(username='other-user')


# --- Pinned Django behavior relied on by _insert_new ---


def test_database_can_return_rows_from_bulk_insert():
    assert connection.features.can_return_rows_from_bulk_insert


@pytest.mark.django_db
def test_private_insert_returns_only_inserted_rows(rando, other_user, inv_rd, inv_object_role):
    """QuerySet._insert with RETURNING and ON CONFLICT DO NOTHING returns only the rows it inserted."""
    opts = RoleUserAssignment._meta
    fields = [f for f in opts.concrete_fields if not f.generated and f is not opts.pk]
    returning_fields = [opts.pk, opts.get_field('user')]
    objs = [_user_assignment(rando, inv_rd, inv_object_role), _user_assignment(other_user, inv_rd, inv_object_role)]

    rows = RoleUserAssignment.objects._insert(objs, fields=fields, returning_fields=returning_fields, on_conflict=OnConflict.IGNORE)

    assert len(rows) == 1
    pk, user_id = rows[0]
    assert user_id == other_user.pk
    assert RoleUserAssignment.objects.get(user=other_user).pk == pk
    assert RoleUserAssignment.objects.filter(object_role=inv_object_role).count() == 2


@pytest.mark.django_db
@pytest.mark.parametrize('n_objs', [1, 3])
def test_private_insert_returns_no_rows_when_all_conflict(rando, inv_rd, inv_object_role, n_objs):
    """When every row conflicts, nothing usable comes back.

    A single-object insert takes Django's one-row path (cursor.fetchone()) and yields [None]
    rather than []; a multi-object insert yields []. _insert_new skips None rows for this reason.
    """
    opts = RoleUserAssignment._meta
    fields = [f for f in opts.concrete_fields if not f.generated and f is not opts.pk]
    objs = [_user_assignment(rando, inv_rd, inv_object_role) for _ in range(n_objs)]
    rows = RoleUserAssignment.objects._insert(objs, fields=fields, returning_fields=[opts.pk], on_conflict=OnConflict.IGNORE)
    assert [row for row in rows if row is not None] == []


# --- _insert_new ---


@pytest.mark.django_db
def test_returns_only_new_user_assignments(rando, other_user, inv_rd, inv_object_role):
    existing = RoleUserAssignment.objects.get(user=rando)
    new = _user_assignment(other_user, inv_rd, inv_object_role)

    created = _insert_new([_user_assignment(rando, inv_rd, inv_object_role), new], 'user_id', RoleUserAssignment)

    assert created == [new]
    assert new is created[0]  # the caller's in-memory object, PK backfilled
    db_row = RoleUserAssignment.objects.get(user=other_user)
    assert new.pk == db_row.pk
    assert new._state.adding is False
    assert db_row.created is not None
    assert RoleUserAssignment.objects.get(user=rando).pk == existing.pk


@pytest.mark.django_db
def test_returns_only_new_team_assignments(team, organization, inv_rd, inventory):
    obj_role = inv_rd.give_permission(team, inventory).object_role
    inv2 = Inventory.objects.create(name='inv2', organization=organization)
    inv_rd.give_permission(team, inv2)  # creates the object role for inv2, then remove the assignment
    obj_role2 = RoleTeamAssignment.objects.get(team=team, object_id=str(inv2.pk)).object_role
    RoleTeamAssignment.objects.filter(team=team, object_role=obj_role2).delete()
    new = _team_assignment(team, inv_rd, obj_role2)

    created = _insert_new([_team_assignment(team, inv_rd, obj_role), new], 'team_id', RoleTeamAssignment)

    assert created == [new]
    assert new.pk == RoleTeamAssignment.objects.get(team=team, object_role=obj_role2).pk


@pytest.mark.django_db
def test_all_existing_returns_empty(rando, inv_rd, inv_object_role):
    before = RoleUserAssignment.objects.count()
    assert _insert_new([_user_assignment(rando, inv_rd, inv_object_role)], 'user_id', RoleUserAssignment) == []
    assert RoleUserAssignment.objects.count() == before


@pytest.mark.django_db
def test_global_assignments_skip_existing_and_keep_role_definitions_distinct(rando, global_inv_rd, global_user_assignment):
    """Partial unique constraints on global assignments are honored; different role definitions stay distinct."""
    other_global_rd = RoleDefinition.objects.create_from_permissions(permissions=['view_inventory'], name='global-view-inv', content_type=None)
    new = _user_assignment(rando, other_global_rd)

    created = _insert_new([_user_assignment(rando, global_inv_rd), new], 'user_id', RoleUserAssignment)

    assert created == [new]
    assert new.pk == RoleUserAssignment.objects.get(user=rando, role_definition=other_global_rd, object_role=None).pk
    assert RoleUserAssignment.objects.filter(user=rando, role_definition=global_inv_rd, object_role=None).count() == 1


@pytest.mark.django_db
def test_mixed_batches(rando, inv_rd, inv_object_role):
    """Rows split across several INSERT statements still map back correctly."""
    users = [User.objects.create(username=f'batch-user-{i}') for i in range(7)]
    objs = [_user_assignment(rando, inv_rd, inv_object_role)] + [_user_assignment(u, inv_rd, inv_object_role) for u in users]

    with mock.patch.object(connection.ops, 'bulk_batch_size', return_value=3):
        created = _insert_new(objs, 'user_id', RoleUserAssignment)

    assert created == objs[1:]
    db_pks = dict(RoleUserAssignment.objects.filter(user__in=users).values_list('user_id', 'pk'))
    assert {o.user_id: o.pk for o in created} == db_pks


@pytest.mark.django_db
def test_concurrent_row_in_id_gap_is_not_reported(rando, other_user, inv_rd, inv_object_role):
    """A row committed by someone else between our inserts is never mistaken for ours."""
    third = User.objects.create(username='third-user')
    real_insert = QuerySet._insert

    def insert_then_interleave(self, objs, *args, **kwargs):
        rows = real_insert(self, objs, *args, **kwargs)
        # simulate another caller creating the same identity we are about to try in the next batch
        if not RoleUserAssignment.objects.filter(user=third).exists():
            RoleUserAssignment.objects.bulk_create([_user_assignment(third, inv_rd, inv_object_role)])
        return rows

    objs = [_user_assignment(other_user, inv_rd, inv_object_role), _user_assignment(third, inv_rd, inv_object_role)]
    with mock.patch.object(connection.ops, 'bulk_batch_size', return_value=1), mock.patch.object(QuerySet, '_insert', insert_then_interleave):
        created = _insert_new(objs, 'user_id', RoleUserAssignment)

    assert created == objs[:1]
    assert objs[1].pk is None
