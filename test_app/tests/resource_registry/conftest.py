from contextlib import contextmanager
from unittest import mock

import pytest

from ansible_base.resource_registry import apps


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
        # DISABLE_RESOURCE_SERVER_SYNC, undo the patch (disconnect_resource_signals),
        # and then reconnect signals (so the resource registry stuff still works) but
        # this time we don't monkeypatch the save method since DISABLE_RESOURCE_SERVER_SYNC
        # is back to its original value.
        is_disabled = settings.DISABLE_RESOURCE_SERVER_SYNC
        settings.DISABLE_RESOURCE_SERVER_SYNC = False
        apps.connect_resource_signals(sender=None)
        if mock_away_sync:
            with mock.patch('ansible_base.resource_registry.utils.sync_to_resource_server.get_resource_server_client'):
                yield
        else:
            yield
        apps.disconnect_resource_signals(sender=None)
        settings.DISABLE_RESOURCE_SERVER_SYNC = is_disabled
        apps.connect_resource_signals(sender=None)

    return f
