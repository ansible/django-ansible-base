"""
Test suite to verify resource_registry works both with and without rbac installed.
This test module specifically tests our conditional rbac functionality.
"""

import pytest
from django.conf import settings
from django.test import override_settings

from ansible_base.resource_registry.constants import (
    SHARED_ORGANIZATION_RESOURCE_TYPE,
    SHARED_ROLE_DEFINITION_RESOURCE_TYPE,
    SHARED_TEAM_RESOURCE_TYPE,
    SHARED_USER_RESOURCE_TYPE,
)
from ansible_base.resource_registry.registry import ServiceAPIConfig
from ansible_base.resource_registry.rest_client import ResourceAPIClient
from ansible_base.resource_registry.shared_types import LenientPermissionSlugListField, RoleDefinitionType


class TestResourceRegistryWithoutRBAC:
    """Test resource registry functionality when rbac is NOT installed."""

    @pytest.fixture(autouse=True)
    def setup_without_rbac(self):
        """Override settings to remove rbac from INSTALLED_APPS for these tests."""
        # Create a copy of INSTALLED_APPS without rbac
        apps_without_rbac = [app for app in settings.INSTALLED_APPS if 'rbac' not in app]

        with override_settings(INSTALLED_APPS=apps_without_rbac):
            yield

    def test_resource_api_client_sync_methods_raise_errors(self):
        """Test that sync methods raise appropriate errors when rbac is not available."""
        client = ResourceAPIClient("http://test", "/test/")

        # Mock assignment object
        class MockAssignment:
            class _meta:
                model_name = 'roleuserassignment'

            def __init__(self):
                self.role_definition = None  # Add the required attribute

        assignment = MockAssignment()

        with pytest.raises(RuntimeError, match="This operation requires ansible_base.rbac to be installed"):
            client.sync_assignment(assignment)

        with pytest.raises(RuntimeError, match="This operation requires ansible_base.rbac to be installed"):
            client.sync_unassignment(None, None, None)

    def test_role_definition_type_raises_error(self):
        """Test that RoleDefinitionType raises error when rbac not available."""
        with pytest.raises(RuntimeError, match="requires ansible_base.rbac to be installed"):
            RoleDefinitionType()

    def test_service_api_config_excludes_role_definition_processor(self):
        """Test that ServiceAPIConfig excludes RoleDefinitionProcessor when rbac not available."""
        processors = ServiceAPIConfig._get_default_resource_processors()

        # Should not include shared.roledefinition when rbac is not installed
        assert SHARED_ROLE_DEFINITION_RESOURCE_TYPE not in processors

        # Should still include other processors
        assert SHARED_USER_RESOURCE_TYPE in processors
        assert SHARED_TEAM_RESOURCE_TYPE in processors
        assert SHARED_ORGANIZATION_RESOURCE_TYPE in processors

    @pytest.mark.django_db
    def test_resource_registry_basic_functionality_works(self):
        """Test that basic resource registry functionality still works without rbac."""
        from ansible_base.resource_registry.models import service_id
        from ansible_base.resource_registry.registry import get_registry

        # These should work without rbac
        current_service_id = service_id()
        assert current_service_id is not None

        # Registry should still work
        registry = get_registry()
        assert registry is not False


class TestResourceRegistryWithRBAC:
    """Test resource registry functionality when rbac IS installed (normal case)."""

    def test_resource_api_client_rbac_methods_work(self):
        """Test that RBAC methods work when rbac is available."""
        # This test runs with rbac installed (default test environment)
        client = ResourceAPIClient("http://test", "/test/")

        # These should not raise RuntimeError (though they may raise other errors due to network/auth)
        # We're just testing that the conditional check passes
        try:
            client.list_role_types()
        except RuntimeError as e:
            if "requires ansible_base.rbac to be installed" in str(e):
                pytest.fail("Should not raise rbac requirement error when rbac is installed")
        except Exception:
            # Other exceptions (network, auth, etc.) are expected and OK
            pass

    def test_role_definition_type_works(self):
        """Test that RoleDefinitionType works when rbac is available."""
        # Should not raise RuntimeError about rbac requirement
        try:
            serializer = RoleDefinitionType()
            # Should have content_type field when rbac is available
            assert 'content_type' in serializer.fields
        except RuntimeError as e:
            if "requires ansible_base.rbac to be installed" in str(e):
                pytest.fail("Should not raise rbac requirement error when rbac is installed")

    def test_lenient_permission_slug_list_field_works(self):
        """Test that LenientPermissionSlugListField works when rbac is available."""
        field = LenientPermissionSlugListField()

        # Should not raise RuntimeError about rbac requirement
        # (though it may raise other validation errors)
        try:
            field.to_internal_value([])
        except RuntimeError as e:
            if "requires ansible_base.rbac to be installed" in str(e):
                pytest.fail("Should not raise rbac requirement error when rbac is installed")
        except Exception:
            # Other exceptions (validation, etc.) are expected and OK
            pass

    def test_service_api_config_includes_role_definition_processor(self):
        """Test that ServiceAPIConfig includes RoleDefinitionProcessor when rbac is available."""
        processors = ServiceAPIConfig._get_default_resource_processors()

        # Should include shared.roledefinition when rbac is installed
        assert SHARED_ROLE_DEFINITION_RESOURCE_TYPE in processors

        # Should also include other processors
        assert SHARED_USER_RESOURCE_TYPE in processors
        assert SHARED_TEAM_RESOURCE_TYPE in processors
        assert SHARED_ORGANIZATION_RESOURCE_TYPE in processors


class TestResourceRegistryConditionalImports:
    """Test the conditional import behavior directly."""

    def test_imports_work_with_rbac(self):
        """Test that conditional imports work when rbac is available."""
        # These imports should work without errors
        from ansible_base.resource_registry import registry, rest_client, shared_types
        from ansible_base.resource_registry.tasks import sync

        # All modules should be importable
        assert rest_client is not None
        assert shared_types is not None
        assert sync is not None
        assert registry is not None

    @override_settings(
        INSTALLED_APPS=[
            'django.contrib.contenttypes',
            'django.contrib.auth',
            'rest_framework',
            'ansible_base.resource_registry',
            'test_app',
        ]
    )
    def test_imports_work_without_rbac(self):
        """Test that conditional imports work when rbac is not available."""
        # Force reload modules to pick up new settings
        import importlib

        from ansible_base.resource_registry import registry, rest_client, shared_types
        from ansible_base.resource_registry.tasks import sync

        # Force reload to pick up the modified INSTALLED_APPS
        importlib.reload(rest_client)
        importlib.reload(shared_types)
        importlib.reload(sync)
        importlib.reload(registry)

        # All modules should still be importable
        assert rest_client is not None
        assert shared_types is not None
        assert sync is not None
        assert registry is not None
