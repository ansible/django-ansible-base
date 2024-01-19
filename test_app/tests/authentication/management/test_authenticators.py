from io import StringIO
from unittest import mock

import pytest
from django.core.management import CommandError, call_command

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


def test_authenticators_cli_initialize(django_user_model):
    """
    Calling with --initialize will create:
    - An authenticator if there is an admin user
    """
    out = StringIO()
    err = StringIO()

    # Sanity check:
    assert django_user_model.objects.count() == 0

    with pytest.raises(SystemExit) as pytest_wrapped_e:
        call_command('authenticators', "--initialize", stdout=out, stderr=err)
    assert pytest_wrapped_e.type == SystemExit
    assert pytest_wrapped_e.value.code == 255
    assert "No admin user exists" in err.getvalue()

    django_user_model.objects.create(username="admin")
    call_command('authenticators', "--initialize", stdout=out, stderr=err)
    assert "Created default local authenticator" in out.getvalue()


def test_authenticators_cli_initialize_pre_existing(django_user_model, local_authenticator, admin_user):
    """
    What if we already have an admin user?

    In this case, the command should do nothing on --initialize.
    """
    out = StringIO()
    err = StringIO()

    # Sanity check:
    assert django_user_model.objects.count() == 1
    existing_user = django_user_model.objects.first()
    assert AuthenticatorUser.objects.count() == 0

    call_command('authenticators', "--initialize", stdout=out, stderr=err)

    # Make sure no new user got created.
    assert django_user_model.objects.count() == 1
    assert django_user_model.objects.filter(username="admin").count() == 1
    new_user = django_user_model.objects.first()

    # Nothing should have changed
    assert existing_user == new_user
    assert existing_user.date_joined == new_user.date_joined
    assert out.getvalue() == ""
    assert err.getvalue() == ""

    # No AuthenticatorUser should get created in this case
    assert AuthenticatorUser.objects.count() == 0


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
