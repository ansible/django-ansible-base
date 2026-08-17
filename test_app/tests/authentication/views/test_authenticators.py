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


@pytest.mark.django_db
def test_patch_authenticator_with_empty_configuration(admin_api_client, ldap_authenticator, ldap_configuration):
    """
    Test that PATCHing an authenticator with an empty configuration dict
    succeeds without requiring all configuration fields to be re-sent.
    Regression test for AAP-45971.
    """
    url = get_relative_url("authenticator-detail", kwargs={'pk': ldap_authenticator.pk})
    response = admin_api_client.patch(url, data={"configuration": {}}, format='json')
    assert response.status_code == 200
    ldap_authenticator.refresh_from_db()
    assert ldap_authenticator.configuration['SERVER_URI'] == ldap_configuration['SERVER_URI']
    assert ldap_authenticator.configuration['USER_ATTR_MAP'] == ldap_configuration['USER_ATTR_MAP']
    assert ldap_authenticator.configuration['GROUP_TYPE'] == ldap_configuration['GROUP_TYPE']


@pytest.mark.django_db
def test_patch_authenticator_without_configuration(admin_api_client, ldap_authenticator, ldap_configuration):
    """
    Test that PATCHing an authenticator with only `enabled` (no configuration
    field at all) succeeds and preserves existing configuration.
    """
    url = get_relative_url("authenticator-detail", kwargs={'pk': ldap_authenticator.pk})
    response = admin_api_client.patch(url, data={"enabled": True}, format='json')
    assert response.status_code == 200
    ldap_authenticator.refresh_from_db()
    assert ldap_authenticator.configuration['SERVER_URI'] == ldap_configuration['SERVER_URI']
