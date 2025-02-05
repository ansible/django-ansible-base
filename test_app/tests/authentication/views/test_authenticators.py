import pytest

from ansible_base.lib.utils.response import get_relative_url


@pytest.mark.django_db
def test_authenticators_view_denies_delete_last_enabled_authenticator(admin_api_client, system_user, local_authenticator):
    """
    Test that the admin can't delete the last enabled authenticator.
    """

    url = get_relative_url("authenticator-detail", kwargs={'pk': local_authenticator.pk})
    response = admin_api_client.delete(url)
    assert response.status_code == 400
    assert response.data['details'] == "Authenticator cannot be deleted, as no authenticators would be enabled"


@pytest.mark.django_db
def test_authenticators_metadata_not_instanced_on_create(admin_api_client, local_authenticator):
    url = get_relative_url("authenticator-list")
    response = admin_api_client.options(url)
    assert response.status_code == 200
    assert response.data['actions']['POST']['slug']["read_only"] is False


def test_authenticators_metadata_instanced_on_update(admin_api_client, local_authenticator):
    url = get_relative_url("authenticator-detail", kwargs={'pk': local_authenticator.pk})
    response = admin_api_client.options(url)
    assert response.status_code == 200
    assert response.data['actions']['PUT']['slug']["read_only"] is True
