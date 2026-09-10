"""Regression tests for AAP-83436: duplicate global role assignments."""

import pytest
from django.db import IntegrityError, transaction

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import RoleTeamAssignment, RoleUserAssignment
from test_app.models import Inventory


@pytest.mark.django_db
class TestGlobalUserAssignmentConstraint:
    def test_idempotent(self, rando, global_inv_rd, global_user_assignment):
        assignment2 = global_inv_rd.give_global_permission(rando)
        assert global_user_assignment.pk == assignment2.pk
        assert RoleUserAssignment.objects.filter(user=rando, role_definition=global_inv_rd, object_role__isnull=True).count() == 1

    @pytest.mark.xfail(raises=IntegrityError, strict=True, reason="DB constraint must reject duplicate global user assignment")
    def test_duplicate_prevented_by_constraint(self, rando, global_inv_rd, global_user_assignment):
        with transaction.atomic():
            RoleUserAssignment.objects.create(user=rando, role_definition=global_inv_rd, object_role=None)

    def test_object_level_assignments_unaffected(self, rando, inv_rd, inventory, organization):
        inv2 = Inventory.objects.create(name='inv2', organization=organization)
        a1 = inv_rd.give_permission(rando, inventory)
        a2 = inv_rd.give_permission(rando, inv2)
        assert a1.pk != a2.pk
        assert a1.role_definition == a2.role_definition

    def test_duplicate_global_assignment_via_api(self, admin_api_client, rando, global_inv_rd):
        url = get_relative_url('roleuserassignment-list')
        data = {'user': rando.pk, 'role_definition': global_inv_rd.pk}
        r1 = admin_api_client.post(url, data=data)
        assert r1.status_code == 201, r1.data
        r2 = admin_api_client.post(url, data=data)
        assert r2.status_code == 201, r2.data
        assert r1.data['id'] == r2.data['id']


@pytest.mark.django_db
class TestGlobalTeamAssignmentConstraint:
    def test_idempotent(self, team, global_inv_rd, global_team_assignment):
        assignment2 = global_inv_rd.give_global_permission(team)
        assert global_team_assignment.pk == assignment2.pk
        assert RoleTeamAssignment.objects.filter(team=team, role_definition=global_inv_rd, object_role__isnull=True).count() == 1

    @pytest.mark.xfail(raises=IntegrityError, strict=True, reason="DB constraint must reject duplicate global team assignment")
    def test_duplicate_prevented_by_constraint(self, team, global_inv_rd, global_team_assignment):
        with transaction.atomic():
            RoleTeamAssignment.objects.create(team=team, role_definition=global_inv_rd, object_role=None)
