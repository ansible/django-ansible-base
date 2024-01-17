from unittest import mock

import pytest
from rest_framework.serializers import ValidationError

from ansible_base.authentication.serializers import AuthenticatorSerializer


@pytest.mark.django_db
def test_removed_authenticator_plugin(ldap_authenticator, shut_up_logging):
    serializer = AuthenticatorSerializer()
    item = serializer.to_representation(ldap_authenticator)
    assert 'error' not in item
    assert 'configuration' in item
    assert item['configuration'] != {}

    # Change the type of the LDAP authenticator
    ldap_authenticator.type = 'junk'
    item = serializer.to_representation(ldap_authenticator)
    assert 'error' in item
    assert 'configuration' in item
    assert item['configuration'] == {}


def test_authenticator_no_configuration(shut_up_logging):
    serializer = AuthenticatorSerializer()
    with pytest.raises(ValidationError):
        serializer.validate(
            {
                "name": "Local Test Authenticator",
                "enabled": True,
                "create_objects": True,
                "users_unique": False,
                "remove_users": False,
                "type": "ansible_base.authentication.authenticator_plugins.local",
                "order": 497,
            }
        )


def test_authenticator_validate_import_error(shut_up_logging):
    serializer = AuthenticatorSerializer()
    with (
        mock.patch(
            "ansible_base.authentication.serializers.authenticator.AuthenticatorSerializer.context",
            return_value={'request': {'method': 'PUT'}},
        ),
        mock.patch(
            "ansible_base.authentication.serializers.authenticator.get_authenticator_plugin",
            side_effect=ImportError(),
        ),
    ):
        with pytest.raises(ValidationError):
            serializer.validate(
                {
                    "name": "Local Test Authenticator",
                    "enabled": True,
                    "create_objects": True,
                    "users_unique": False,
                    "remove_users": False,
                    "configuration": {},
                    "type": "ansible_base.authentication.authenticator_plugins.local",
                    "order": 497,
                }
            )
