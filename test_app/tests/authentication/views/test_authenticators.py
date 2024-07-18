import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_authenticators_view_denies_delete_last_enabled_authenticator(admin_api_client, system_user, local_authenticator):
    """
    Test that the admin can't delete the last enabled authenticator.
    """

    url = reverse("authenticator-detail", kwargs={'pk': local_authenticator.pk})
    response = admin_api_client.delete(url)
    assert response.status_code == 400
    assert response.data['details'] == "Authenticator cannot be deleted, as no authenticators would be enabled"
