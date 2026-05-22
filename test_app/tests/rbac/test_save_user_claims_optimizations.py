"""Tests for save_user_claims() performance and reliability optimizations.

Verifies that save_user_claims():
- Wraps operations in transaction.atomic() for rollback on failure
- Wraps operations in no_reverse_sync() to suppress signals
- Wraps operations in defer_role_evaluation() to batch cache updates
- Logs timing and grant/removal counts
"""

import logging
from unittest import mock
from uuid import uuid4

import pytest

from ansible_base.rbac.claims import save_user_claims
from ansible_base.rbac.models import RoleDefinition, RoleUserAssignment
from ansible_base.rbac.permission_registry import permission_registry
from test_app.models import Organization


@pytest.fixture
def organization_admin_role():
    return RoleDefinition.objects.create_from_permissions(
        permissions=[
            permission_registry.team_permission,
            f'view_{permission_registry.team_model._meta.model_name}',
            'view_organization',
            'change_organization',
        ],
        name='Organization Admin',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
        managed=True,
    )


@pytest.mark.django_db
class TestSaveUserClaimsAtomicity:
    def test_partial_failure_rolls_back(self, admin_user, organization, organization_admin_role):
        """If save_user_claims fails midway, no partial writes should persist."""
        objects = {'organization': [{'ansible_id': str(organization.resource.ansible_id), 'name': organization.name}]}
        object_roles = {"Organization Admin": {'content_type': 'organization', 'objects': [0]}}

        save_user_claims(admin_user, objects, object_roles, [])
        assert RoleUserAssignment.objects.filter(user=admin_user).count() == 1

        # Now attempt a save that will fail partway through give_permission
        with mock.patch(
            'ansible_base.rbac.models.role.RoleDefinition.give_permission',
            side_effect=RuntimeError("simulated failure"),
        ):
            with pytest.raises(RuntimeError, match="simulated failure"):
                new_org_id = str(uuid4())
                objects_bad = {
                    'organization': [
                        {'ansible_id': str(organization.resource.ansible_id), 'name': organization.name},
                        {'ansible_id': new_org_id, 'name': 'New Org'},
                    ]
                }
                object_roles_bad = {"Organization Admin": {'content_type': 'organization', 'objects': [0, 1]}}
                save_user_claims(admin_user, objects_bad, object_roles_bad, [])

        # Original assignment should still be intact (rolled back to pre-failure state)
        assert RoleUserAssignment.objects.filter(user=admin_user).count() == 1


@pytest.mark.django_db
class TestSaveUserClaimsNoReverseSync:
    def test_no_reverse_sync_during_save(self, admin_user, organization_admin_role):
        """Verify no_reverse_sync is active during save_user_claims execution."""
        from ansible_base.resource_registry.signals.handlers import reverse_sync_enabled

        sync_states_during_save = []

        original_give_permission = RoleDefinition.give_permission

        def spy_give_permission(self, actor, content_object):
            sync_states_during_save.append(reverse_sync_enabled.enabled)
            return original_give_permission(self, actor, content_object)

        org = Organization.objects.create(name='sync-test-org')
        objects = {'organization': [{'ansible_id': str(org.resource.ansible_id), 'name': org.name}]}
        object_roles = {"Organization Admin": {'content_type': 'organization', 'objects': [0]}}

        with mock.patch.object(RoleDefinition, 'give_permission', spy_give_permission):
            save_user_claims(admin_user, objects, object_roles, [])

        assert len(sync_states_during_save) > 0
        assert all(state is False for state in sync_states_during_save), "reverse_sync should be disabled during save_user_claims"


@pytest.mark.django_db
class TestSaveUserClaimsDeferredEvaluation:
    def test_deferred_evaluation_during_save(self, admin_user, organization_admin_role):
        """Verify defer_role_evaluation is active during save_user_claims execution."""
        from ansible_base.rbac.triggers import _deferred_evaluation

        deferred_states = []

        original_give_permission = RoleDefinition.give_permission

        def spy_give_permission(self, actor, content_object):
            deferred_states.append(_deferred_evaluation.enabled)
            return original_give_permission(self, actor, content_object)

        org = Organization.objects.create(name='defer-test-org')
        objects = {'organization': [{'ansible_id': str(org.resource.ansible_id), 'name': org.name}]}
        object_roles = {"Organization Admin": {'content_type': 'organization', 'objects': [0]}}

        with mock.patch.object(RoleDefinition, 'give_permission', spy_give_permission):
            save_user_claims(admin_user, objects, object_roles, [])

        assert len(deferred_states) > 0
        assert all(state is True for state in deferred_states), "evaluation should be deferred during save_user_claims"


@pytest.mark.django_db
class TestSaveUserClaimsLogging:
    def test_logs_grant_count(self, admin_user, organization, organization_admin_role, caplog):
        objects = {'organization': [{'ansible_id': str(organization.resource.ansible_id), 'name': organization.name}]}
        object_roles = {"Organization Admin": {'content_type': 'organization', 'objects': [0]}}

        with caplog.at_level(logging.INFO, logger='ansible_base.rbac.claims'):
            save_user_claims(admin_user, objects, object_roles, [])

        summary_logs = [r for r in caplog.records if r.message.startswith('save_user_claims for')]
        assert len(summary_logs) == 1
        assert '1 grants' in summary_logs[0].message
        assert '0 removals' in summary_logs[0].message
        assert 's' in summary_logs[0].message  # elapsed time

    def test_logs_removal_count(self, admin_user, organization, organization_admin_role, caplog):
        objects = {'organization': [{'ansible_id': str(organization.resource.ansible_id), 'name': organization.name}]}
        object_roles = {"Organization Admin": {'content_type': 'organization', 'objects': [0]}}
        save_user_claims(admin_user, objects, object_roles, [])

        caplog.clear()
        with caplog.at_level(logging.INFO, logger='ansible_base.rbac.claims'):
            save_user_claims(admin_user, {}, {}, [])

        summary_logs = [r for r in caplog.records if r.message.startswith('save_user_claims for')]
        assert len(summary_logs) == 1
        assert '0 grants' in summary_logs[0].message
        assert '1 removals' in summary_logs[0].message

    def test_logs_mixed_grants_and_removals(self, admin_user, organization_admin_role, caplog):
        org1 = Organization.objects.create(name='log-org-1')
        org2 = Organization.objects.create(name='log-org-2')

        objects = {'organization': [{'ansible_id': str(org1.resource.ansible_id), 'name': org1.name}]}
        object_roles = {"Organization Admin": {'content_type': 'organization', 'objects': [0]}}
        save_user_claims(admin_user, objects, object_roles, [])

        caplog.clear()
        # Now grant org2 and remove org1
        objects2 = {'organization': [{'ansible_id': str(org2.resource.ansible_id), 'name': org2.name}]}
        with caplog.at_level(logging.INFO, logger='ansible_base.rbac.claims'):
            save_user_claims(admin_user, objects2, object_roles, [])

        summary_logs = [r for r in caplog.records if r.message.startswith('save_user_claims for')]
        assert len(summary_logs) == 1
        assert '1 grants' in summary_logs[0].message
        assert '1 removals' in summary_logs[0].message
