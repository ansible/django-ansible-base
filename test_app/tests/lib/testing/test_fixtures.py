import pytest

from ansible_base.lib.testing.fixtures import _get_or_create_admin_user, _get_or_create_local_authenticator, _login_admin_api_client
from ansible_base.lib.utils.response import get_relative_url


@pytest.mark.django_db
def test_get_or_create_local_authenticator_is_idempotent():
    """Second call returns the same row instead of creating a duplicate."""
    first = _get_or_create_local_authenticator()
    second = _get_or_create_local_authenticator()
    assert first.pk == second.pk
    assert first.name == "Test Local Authenticator"


@pytest.mark.django_db
def test_get_or_create_admin_user_creates_when_missing(django_user_model):
    assert not django_user_model.objects.filter(username="admin").exists()

    user = _get_or_create_admin_user(django_user_model)

    assert user.username == "admin"
    assert user.is_superuser
    assert user.check_password("password")


@pytest.mark.django_db
def test_get_or_create_admin_user_normalizes_existing(django_user_model):
    """A pre-existing "admin" row (e.g. surviving --reuse-db) gets fixed up
    rather than left stale -- inactive/non-superuser/wrong password."""
    django_user_model.objects.create_user(username="admin", password="wrong", is_active=False, is_superuser=False)

    user = _get_or_create_admin_user(django_user_model)

    assert user.is_active
    assert user.is_superuser
    assert user.check_password("password")


@pytest.mark.django_db
def test_login_admin_api_client(admin_user, local_authenticator):
    client, login_ok = _login_admin_api_client(admin_user)
    assert login_ok
    response = client.get(get_relative_url("user-list"))
    assert response.status_code == 200


def test_settings_override_mutable(settings_override_mutable, settings):
    """
    Ensure that when we modify a mutable setting, it gets reverted.
    """
    assert settings.LOGGING['handlers']['console']['formatter'] == "simple"

    with settings_override_mutable('LOGGING'):
        settings.LOGGING['handlers']['console']['formatter'] = "not so simple"
        assert settings.LOGGING['handlers']['console']['formatter'] == "not so simple"

        del settings.LOGGING['handlers']['console']['formatter']
        assert 'formattter' not in settings.LOGGING['handlers']['console']

    assert settings.LOGGING['handlers']['console']['formatter'] == "simple"
