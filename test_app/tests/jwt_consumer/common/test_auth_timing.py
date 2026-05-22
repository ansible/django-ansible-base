"""Tests for timing logs in process_rbac_permissions()."""

import logging
from unittest import mock

import pytest

from ansible_base.jwt_consumer.common.auth import JWTCommonAuth


@pytest.mark.django_db
class TestProcessRbacPermissionsTiming:
    def test_logs_timing_on_successful_reconciliation(self, admin_user, caplog):
        """Verify timing breakdown is logged after a successful gateway fetch + save."""
        authentication = JWTCommonAuth()
        authentication.user = admin_user
        user_ansible_id = "12345678-1234-5678-9abc-123456789012"
        authentication.token = {
            "sub": user_ansible_id,
            "claims_hash": "new_hash",
        }

        gateway_response = {
            'objects': {},
            'object_roles': {},
            'global_roles': [],
        }

        with (
            mock.patch.object(authentication.cache, 'get_cached_claims_hash', return_value=None),
            mock.patch.object(authentication.cache, 'cache_claims_hash'),
            mock.patch('ansible_base.rbac.claims.get_user_claims', return_value={}),
            mock.patch('ansible_base.rbac.claims.get_user_claims_hashable_form', return_value={}),
            mock.patch('ansible_base.rbac.claims.get_claims_hash', return_value="different_hash"),
            mock.patch.object(authentication, '_fetch_jwt_claims_from_gateway', return_value=gateway_response),
            mock.patch('ansible_base.rbac.claims.save_user_claims') as mock_save,
            caplog.at_level(logging.INFO, logger='ansible_base.jwt_consumer.common.auth'),
        ):
            authentication.process_rbac_permissions()

        mock_save.assert_called_once()

        timing_logs = [r for r in caplog.records if 'Claims reconciliation' in r.message]
        assert len(timing_logs) == 1
        msg = timing_logs[0].message
        assert f'Claims reconciliation for {user_ansible_id}' in msg
        assert 'fetch=' in msg
        assert 'save=' in msg
        assert 'total=' in msg

    def test_no_timing_log_on_cache_hit(self, admin_user, caplog):
        """Cache hit should return early with no timing log."""
        authentication = JWTCommonAuth()
        authentication.user = admin_user
        authentication.token = {
            "sub": "12345678-1234-5678-9abc-123456789012",
            "claims_hash": "cached_hash",
        }

        with (
            mock.patch.object(authentication.cache, 'get_cached_claims_hash', return_value="cached_hash"),
            caplog.at_level(logging.INFO, logger='ansible_base.jwt_consumer.common.auth'),
        ):
            authentication.process_rbac_permissions()

        timing_logs = [r for r in caplog.records if 'Claims reconciliation' in r.message]
        assert len(timing_logs) == 0

    def test_no_timing_log_on_local_match(self, admin_user, caplog):
        """Local hash match should return early with no timing log."""
        authentication = JWTCommonAuth()
        authentication.user = admin_user
        authentication.token = {
            "sub": "12345678-1234-5678-9abc-123456789012",
            "claims_hash": "matching_hash",
        }

        with (
            mock.patch.object(authentication.cache, 'get_cached_claims_hash', return_value=None),
            mock.patch('ansible_base.rbac.claims.get_user_claims', return_value={}),
            mock.patch('ansible_base.rbac.claims.get_user_claims_hashable_form', return_value={}),
            mock.patch('ansible_base.rbac.claims.get_claims_hash', return_value="matching_hash"),
            caplog.at_level(logging.INFO, logger='ansible_base.jwt_consumer.common.auth'),
        ):
            authentication.process_rbac_permissions()

        timing_logs = [r for r in caplog.records if 'Claims reconciliation' in r.message]
        assert len(timing_logs) == 0

    def test_no_timing_log_on_gateway_failure(self, admin_user, caplog):
        """Gateway failure should raise, not log timing."""
        authentication = JWTCommonAuth()
        authentication.user = admin_user
        authentication.token = {
            "sub": "12345678-1234-5678-9abc-123456789012",
            "claims_hash": "new_hash",
            "user_data": {"is_superuser": False},
        }

        with (
            mock.patch.object(authentication.cache, 'get_cached_claims_hash', return_value=None),
            mock.patch('ansible_base.rbac.claims.get_user_claims', return_value={}),
            mock.patch('ansible_base.rbac.claims.get_user_claims_hashable_form', return_value={}),
            mock.patch('ansible_base.rbac.claims.get_claims_hash', return_value="different_hash"),
            mock.patch.object(authentication, '_fetch_jwt_claims_from_gateway', side_effect=Exception("network error")),
            caplog.at_level(logging.INFO, logger='ansible_base.jwt_consumer.common.auth'),
        ):
            with pytest.raises(Exception, match="Unable to validate user permissions"):
                authentication.process_rbac_permissions()

        timing_logs = [r for r in caplog.records if 'Claims reconciliation' in r.message]
        assert len(timing_logs) == 0
