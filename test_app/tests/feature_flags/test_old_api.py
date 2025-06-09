from rest_framework.test import APIClient

from ansible_base.lib.utils.response import get_relative_url


def test_feature_flags_state_api_list(admin_api_client: APIClient):
    """
    Test that we can list all feature flags
    """
    url = get_relative_url("feature-flags-state-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
