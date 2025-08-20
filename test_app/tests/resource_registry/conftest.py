from contextlib import contextmanager
from unittest import mock

import pytest

from ansible_base.rbac import permission_registry
from ansible_base.resource_registry import apps
from test_app.models import Organization


@pytest.fixture
def enable_reverse_sync(settings):
    """
    Useful for tests that deal with testing the reverse sync logic
    """

    @contextmanager
    def f(mock_away_sync=False):
        # This is kind of a dance. We don't want to break other tests by
        # leaving the save method monkeypatched when they are expecting syncing
        # to be disabled. So we patch the save method, yield, reset
        # RESOURCE_SERVER_SYNC_ENABLED, undo the patch (disconnect_resource_signals),
        # and then reconnect signals (so the resource registry stuff still works) but
        # this time we don't monkeypatch the save method since RESOURCE_SERVER_SYNC_ENABLED
        # is back to its original value.
        is_enabled = settings.RESOURCE_SERVER_SYNC_ENABLED
        settings.RESOURCE_SERVER_SYNC_ENABLED = True
        apps.connect_resource_signals(sender=None)
        if mock_away_sync:
            with mock.patch('ansible_base.resource_registry.utils.sync_to_resource_server.get_resource_server_client'):
                yield
        else:
            yield
        apps.disconnect_resource_signals(sender=None)
        settings.RESOURCE_SERVER_SYNC_ENABLED = is_enabled
        apps.connect_resource_signals(sender=None)

    return f


@pytest.fixture
def foo_type():
    "Idea is that this is a remote type, in this case, the foo type"
    org_ct = permission_registry.content_type_model.objects.get_for_model(Organization)
    return permission_registry.content_type_model.objects.create(service='foo', model='foo', app_label='foo', parent_content_type=org_ct)
