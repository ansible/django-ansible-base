from contextlib import contextmanager
from unittest import mock

import pytest
from django.test.utils import override_settings

from ansible_base.rbac import permission_registry
from ansible_base.resource_registry import apps
from test_app.models import Organization


@pytest.fixture
def enable_reverse_sync():
    """
    Useful for tests that deal with testing the reverse sync logic
    """

    @contextmanager
    def f(mock_away_sync=False):
        # Use Django's override_settings to properly scope the setting change
        # This avoids the scope issues with directly modifying the settings object
        try:
            with override_settings(RESOURCE_SERVER_SYNC_ENABLED=True):
                # Connect signals with the new setting in effect
                apps.connect_resource_signals(sender=None)
                if mock_away_sync:
                    with mock.patch('ansible_base.resource_registry.utils.sync_to_resource_server.get_resource_server_client'):
                        yield
                else:
                    yield
        finally:
            # Clean up signals when exiting the context
            apps.disconnect_resource_signals(sender=None)
            # Reconnect signals with the original setting restored
            apps.connect_resource_signals(sender=None)

    return f


@pytest.fixture
def foo_type():
    "Idea is that this is a remote type, in this case, the foo type"
    org_ct = permission_registry.content_type_model.objects.get_for_model(Organization)
    return permission_registry.content_type_model.objects.create(service='foo', model='foo', app_label='foo', parent_content_type=org_ct)
