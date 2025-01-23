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


def test_feature_flags_api_get(admin_api_client):
    """
    Test that we can get an individual feature flag
    """
    url = get_relative_url("featureflags-detail", args=['FEATURE_SOME_PLATFORM_FLAG_ENABLED'])
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert 'FEATURE_SOME_PLATFORM_FLAG_ENABLED' in response.data
    assert 'FEATURE_SOME_PLATFORM_FLAG_FOO_ENABLED' not in response.data
    assert len(response.data["FEATURE_SOME_PLATFORM_FLAG_ENABLED"]) == 2  # Check conditions returned


def test_feature_flags_api_get_case_insensitive(admin_api_client):
    """
    Test that we can get an individual feature flag (case insensitive)
    """

    url = get_relative_url("featureflags-detail", args=['feature_some_platform_flag_enabled'])
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert 'FEATURE_SOME_PLATFORM_FLAG_ENABLED' in response.data
    assert 'FEATURE_SOME_PLATFORM_FLAG_FOO_ENABLED' not in response.data
    assert len(response.data["FEATURE_SOME_PLATFORM_FLAG_ENABLED"]) == 2  # Check conditions returned


def test_feature_flags_api_get_non_existent(admin_api_client):
    """
    Test that we get 404 when trying to retrieve a non existent feature flag
    """

    url = get_relative_url("featureflags-detail", args=['I_DONT_EXIST'])
    response = admin_api_client.get(url)
    assert response.status_code == 404
