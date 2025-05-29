from rest_framework.test import APIClient

from ansible_base.lib.utils.response import get_relative_url


def test_feature_flags_state_api_list(admin_api_client: APIClient):
    """
    Test that we can list all feature flags
    """
    url = get_relative_url("featureflags-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert 'FEATURE_EDA_ANALYTICS_ENABLED' in response.data
    assert response.data["FEATURE_EDA_ANALYTICS_ENABLED"] is False
    assert 'FEATURE_INDIRECT_NODE_COUNTING_ENABLED' in response.data
    assert response.data["FEATURE_INDIRECT_NODE_COUNTING_ENABLED"] is False
