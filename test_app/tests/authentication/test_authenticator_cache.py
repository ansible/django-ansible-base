from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import pytest
from django.db.models import Count, Max

from ansible_base.authentication.authenticator_cache import get_authenticator_cache_version, load_authenticator_plugins


@pytest.mark.parametrize(
    ("aggregate_result", "expected_version"),
    [
        ({"last_modified": None, "count": 0}, (None, 0)),
        ({"last_modified": "2026-11-03T12:00:00Z", "count": 2}, ("2026-11-03T12:00:00Z", 2)),
    ],
)
def test_get_authenticator_cache_version_uses_shared_database_aggregate(aggregate_result, expected_version):
    authenticators = Mock()
    authenticators.aggregate.return_value = aggregate_result

    assert get_authenticator_cache_version(authenticators) == expected_version
    authenticators.aggregate.assert_called_once_with(last_modified=Max("modified"), count=Count("id"))


def test_load_authenticator_plugins_preserves_authenticator_order_and_skips_unavailable_plugins():
    first = SimpleNamespace(id=7, type="available.first")
    unavailable = SimpleNamespace(id=8, type="unavailable")
    second = SimpleNamespace(id=9, type="available.second")
    first_plugin = Mock()
    second_plugin = Mock()

    with patch(
        "ansible_base.authentication.authenticator_cache.get_authenticator_plugin",
        side_effect=[first_plugin, ImportError, second_plugin],
    ) as get_plugin:
        plugins = load_authenticator_plugins([first, unavailable, second])

    assert plugins == OrderedDict([(first.id, first_plugin), (second.id, second_plugin)])
    assert get_plugin.call_args_list == [call(first.type), call(unavailable.type), call(second.type)]
    first_plugin.update_if_needed.assert_called_once_with(first)
    second_plugin.update_if_needed.assert_called_once_with(second)


def test_load_authenticator_plugins_propagates_unexpected_configuration_errors():
    authenticator = SimpleNamespace(id=7, type="available")
    plugin = Mock()
    plugin.update_if_needed.side_effect = RuntimeError("invalid configuration")

    with (
        patch("ansible_base.authentication.authenticator_cache.get_authenticator_plugin", return_value=plugin),
        pytest.raises(RuntimeError, match="invalid configuration"),
    ):
        load_authenticator_plugins([authenticator])
