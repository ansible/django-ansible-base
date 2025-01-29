from django.test import override_settings
from rest_framework.test import APIClient

from ansible_base.lib.utils.response import get_relative_url


def test_feature_flags_state_api_list(admin_api_client: APIClient):
    """
    Test that we can list all feature flags
    """
    url = get_relative_url("featureflags-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert 'FEATURE_SOME_PLATFORM_FLAG_ENABLED' in response.data
    assert response.data["FEATURE_SOME_PLATFORM_FLAG_ENABLED"] is False
    assert 'FEATURE_SOME_PLATFORM_FLAG_FOO_ENABLED' in response.data
    assert response.data["FEATURE_SOME_PLATFORM_FLAG_FOO_ENABLED"] is False
    assert 'FEATURE_SOME_PLATFORM_FLAG_BAR_ENABLED' in response.data
    assert response.data["FEATURE_SOME_PLATFORM_FLAG_BAR_ENABLED"] is True


@override_settings(
    FLAGS={
        "FEATURE_SOME_PLATFORM_OVERRIDE_ENABLED": [
            {"condition": "boolean", "value": False},
            {"condition": "before date", "value": "2022-06-01T12:00Z"},
        ],
        "FEATURE_SOME_PLATFORM_OVERRIDE_TRUE_ENABLED": [
            {"condition": "boolean", "value": True},
        ],
    }
)
def test_feature_flags_state_api_list_settings_override(admin_api_client: APIClient):
    """
    Test that we can list all feature flags
    """
    url = get_relative_url("featureflags-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert 'FEATURE_SOME_PLATFORM_FLAG_ENABLED' not in response.data
    assert 'FEATURE_SOME_PLATFORM_FLAG_FOO_ENABLED' not in response.data
    assert 'FEATURE_SOME_PLATFORM_FLAG_BAR_ENABLED' not in response.data
    assert 'FEATURE_SOME_PLATFORM_OVERRIDE_ENABLED' in response.data
    assert response.data["FEATURE_SOME_PLATFORM_OVERRIDE_ENABLED"] is False
    assert 'FEATURE_SOME_PLATFORM_OVERRIDE_TRUE_ENABLED' in response.data
    assert response.data["FEATURE_SOME_PLATFORM_OVERRIDE_TRUE_ENABLED"] is True


@override_settings(FLAGS={})
def test_feature_flags_state_api_list_settings_override_empty(admin_api_client: APIClient):
    """
    Test that we can list all feature flags
    """
    url = get_relative_url("featureflags-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data == {}
