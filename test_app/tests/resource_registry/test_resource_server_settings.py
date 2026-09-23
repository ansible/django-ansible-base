import pytest
from django.test import override_settings

from ansible_base.resource_registry.resource_server import get_resource_server_config

VALID_CONFIG = {"URL": "http://localhost", "SECRET_KEY": "my secret key"}


def test_config_returns_defaults():
    with override_settings(RESOURCE_SERVER=dict(VALID_CONFIG)):
        config = get_resource_server_config()

    assert config["URL"] == "http://localhost"
    assert config["SECRET_KEY"] == "my secret key"
    assert config["JWT_ALGORITHM"] == "HS256"
    assert config["VALIDATE_HTTPS"] is True


@pytest.mark.parametrize(
    "config,missing",
    (
        ({}, "URL"),
        ({"SECRET_KEY": "my secret key"}, "URL"),
        ({"URL": "http://localhost"}, "SECRET_KEY"),
    ),
)
def test_missing_required_key_raises(config, missing):
    with override_settings(RESOURCE_SERVER=config):
        with pytest.raises(KeyError, match=missing):
            get_resource_server_config()
