from rest_framework.test import APIClient

from ansible_base.lib.utils.response import get_relative_url


def test_feature_flags_api_list(admin_api_client: APIClient):
    """
    Test that we can list all feature flags
    """
    url = get_relative_url("featureflags-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert 'FEATURE_SOME_PLATFORM_FLAG_ENABLED' in response.data
    assert 'FEATURE_SOME_PLATFORM_FLAG_FOO_ENABLED' in response.data
    assert 'FEATURE_SOME_PLATFORM_FLAG_BAR_ENABLED' in response.data
    assert len(response.data["FEATURE_SOME_PLATFORM_FLAG_FOO_ENABLED"]) == 2  # Check conditions returned
