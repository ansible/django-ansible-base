from io import StringIO
from unittest import mock

import pytest
from django.core.management import CommandError, call_command
from django.test.utils import override_settings

from ansible_base.authentication.models import Authenticator, AuthenticatorUser


@pytest.mark.parametrize(
    "command_args",
    [None, "--list"],
)
def test_authenticators_cli_list_with_tabulate(command_args, local_authenticator, ldap_authenticator):
    """
    When we have tabulate, we have to parse a fancy table.

    Ensure that table contains the authenticators we expect.
    """
    out = StringIO()
    err = StringIO()

    if command_args is None:
        call_command('authenticators', stdout=out, stderr=err)
    else:
        call_command('authenticators', command_args, stdout=out, stderr=err)

    lines = out.getvalue().strip().splitlines()
    headers = ("ID", "Enabled", "Name", "Order")

    for header in headers:
        assert header in lines[0]

    for line, authenticator in ((2, local_authenticator), (3, ldap_authenticator)):
        auth_line = lines[line]
        auth_line = auth_line.strip('|')
        (auth_id, enabled, name, order) = auth_line.split(' | ')

        assert auth_id.strip() == str(authenticator.id)
        assert enabled.strip() == str(authenticator.enabled)
        assert name.strip() == str(authenticator.name)
        assert order.strip() == str(authenticator.order)


@pytest.mark.parametrize(
    "command_args",
    [None, "--list"],
)
@mock.patch("ansible_base.authentication.management.commands.authenticators.HAS_TABULATE", False)
def test_authenticators_cli_list_without_tabulate(command_args, local_authenticator, ldap_authenticator):
    """
    When we don't have tabulate, we have to parse a simple table.

    Ensure that table contains the authenticators we expect.
    """
    out = StringIO()
    err = StringIO()

    if command_args is None:
        call_command('authenticators', stdout=out, stderr=err)
    else:
        call_command('authenticators', command_args, stdout=out, stderr=err)

    lines = out.getvalue().strip().splitlines()
    headers = ("ID", "Enabled", "Name", "Order")

    for header in headers:
        assert header in lines[0]

    for line, authenticator in ((1, local_authenticator), (2, ldap_authenticator)):
        auth_line = lines[line]
        (auth_id, enabled, name, order) = auth_line.split('\t')

        assert auth_id.strip() == str(authenticator.id)
        assert enabled.strip() == str(authenticator.enabled)
        assert name.strip() == str(authenticator.name)
        assert order.strip() == str(authenticator.order)


@pytest.mark.parametrize(
    "system_user_exists,admin_user_exists,log_location,expected_log_entry,expected_authenticator_creator",
    [
        (True, True, "stdout", "Created default local authenticator", "_system"),
        (True, False, "stdout", "Created default local authenticator", "_system"),
        (False, True, "stdout", "Created default local authenticator", "admin"),
        (False, False, "stderr", "Neither system user nor admin user were defined", None),
    ],
)
def test_authenticators_cli_initialize(
    django_user_model, system_user_exists, admin_user_exists, log_location, expected_log_entry, expected_authenticator_creator
):
    """
    Tests the different options for --initialize on authenticators.
    """
    out = StringIO()
    err = StringIO()

    # Sanity check:
    assert django_user_model.objects.count() == 1

    # Optionally create admin user
    if admin_user_exists:
        django_user_model.objects.create(username="admin")

    # Set system user
    system_username = "_system" if system_user_exists else None
    with override_settings(SYSTEM_USERNAME=system_username):
        call_command('authenticators', "--initialize", stdout=out, stderr=err)

        if log_location == "stdout":
            assert expected_log_entry in out.getvalue()
        else:
            assert expected_log_entry in err.getvalue()

        assert Authenticator.objects.count() == 1
        if admin_user_exists or system_user_exists:
            assert Authenticator.objects.first().created_by.username == expected_authenticator_creator
        else:
            assert Authenticator.objects.first().created_by is None


def test_authenticators_cli_initialize_pre_existing(django_user_model, local_authenticator, admin_user, unauthenticated_api_client):
    """
    What if we already have an admin user?

    In this case, the command should do nothing on --initialize.
    """
    out = StringIO()
    err = StringIO()

    # Sanity check:
    assert django_user_model.objects.count() == 2
    existing_user = django_user_model.objects.first()
    assert AuthenticatorUser.objects.count() == 0

    call_command('authenticators', "--initialize", stdout=out, stderr=err)

    # Make sure no new user got created.
    assert django_user_model.objects.count() == 2
    assert django_user_model.objects.filter(username="admin").count() == 1
    new_user = django_user_model.objects.first()

    # Nothing should have changed
    assert existing_user == new_user
    assert existing_user.date_joined == new_user.date_joined
    assert "Local authenticator already exists, skipping" in out.getvalue()
    assert err.getvalue() == ""

    # No AuthenticatorUser should get created in this case
    assert AuthenticatorUser.objects.count() == 0

    # Log in to auto-create AuthenticatorUser
    unauthenticated_api_client.login(username="admin", password="password")
    assert AuthenticatorUser.objects.count() == 1
    assert AuthenticatorUser.objects.first().user == admin_user


@pytest.mark.parametrize(
    "start_state, flag, end_state, exp_out, exp_err",
    [
        pytest.param(False, "--enable", True, "", "", id="disabled -> enabled"),
        pytest.param(False, "--disable", False, "", "", id="disabled -> disabled"),
        pytest.param(True, "--enable", True, "", "", id="enabled -> enabled"),
        pytest.param(True, "--disable", False, "", "", id="enabled -> disabled"),
    ],
)
def test_authenticators_cli_enable_disable(local_authenticator, start_state, flag, end_state, exp_out, exp_err):
    """
    Test enabling/disabling an authenticator.
    """
    local_authenticator.enabled = start_state
    local_authenticator.save()

    out = StringIO()
    err = StringIO()

    assert Authenticator.objects.get(id=local_authenticator.id).enabled == start_state
    call_command('authenticators', flag, local_authenticator.id, stdout=out, stderr=err)
    assert Authenticator.objects.get(id=local_authenticator.id).enabled == end_state

    assert out.getvalue() == exp_out
    assert err.getvalue() == exp_err


@pytest.mark.parametrize(
    "flag",
    ["--enable", "--disable"],
)
@pytest.mark.django_db
def test_authenticators_cli_enable_disable_nonexisting(flag):
    """
    Test enabling/disabling a non-existing authenticator.
    """

    out = StringIO()
    err = StringIO()

    with pytest.raises(CommandError) as e:
        call_command('authenticators', flag, 1337, stdout=out, stderr=err)

    assert "Authenticator 1337 does not exist" in str(e.value)


@pytest.mark.parametrize(
    "fallback_setting,expected_config",
    [
        (["test_fallback_auth"], {"fallback_authentication": ["test_fallback_auth"]}),
        (["auth1", "auth2"], {"fallback_authentication": ["auth1", "auth2"]}),
        ([], {}),
        (None, {}),
    ],
)
def test_authenticators_cli_initialize_with_fallback_setting(django_user_model, fallback_setting, expected_config):
    """
    Test that the ANSIBLE_BASE_AUTHENTICATION_LOCAL_FALLBACK_AUTHENTICATORS setting
    is properly applied when initializing the local authenticator.
    """
    out = StringIO()
    err = StringIO()

    # Ensure no authenticators exist initially
    assert Authenticator.objects.count() == 0

    # Create admin user for the test
    django_user_model.objects.create(username="admin")

    with override_settings(ANSIBLE_BASE_AUTHENTICATION_LOCAL_FALLBACK_AUTHENTICATORS=fallback_setting):
        call_command('authenticators', "--initialize", stdout=out, stderr=err)

        assert Authenticator.objects.count() == 1
        authenticator = Authenticator.objects.first()
        assert authenticator.name == "Local Database Authenticator"
        assert authenticator.type == "ansible_base.authentication.authenticator_plugins.local"
        assert authenticator.configuration == expected_config


def test_authenticators_cli_initialize_fallback_setting_preserves_existing_config(django_user_model, local_authenticator):
    """
    Test that when a local authenticator already exists, the initialize command
    doesn't modify its configuration even if the fallback setting is present.
    """
    out = StringIO()
    err = StringIO()

    # Store the original configuration
    original_config = local_authenticator.configuration.copy()

    with override_settings(ANSIBLE_BASE_AUTHENTICATION_LOCAL_FALLBACK_AUTHENTICATORS=["test_fallback"]):
        call_command('authenticators', "--initialize", stdout=out, stderr=err)

        # Should still only have one authenticator
        assert Authenticator.objects.count() == 1
        authenticator = Authenticator.objects.first()

        # Configuration should remain unchanged
        assert authenticator.configuration == original_config
        assert "Local authenticator already exists, skipping" in out.getvalue()
