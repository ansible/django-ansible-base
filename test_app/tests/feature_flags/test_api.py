import pytest
from rest_framework.test import APIClient

from ansible_base.lib.utils.response import get_relative_url


@pytest.mark.parametrize(
    'feature_flag_name, feature_flag_value',
    [
        ("FEATURE_FEATURE_FLAGS_ENABLED", True),
        ("FEATURE_INDIRECT_NODE_COUNTING_ENABLED", False),
        ("FEATURE_POLICY_AS_CODE_ENABLED", False),
        ("FEATURE_EDA_ANALYTICS_ENABLED", False),
    ],
)
def test_feature_flags_states_api_list(admin_api_client: APIClient, feature_flag_name: str, feature_flag_value: str):
    """
    Test that we can list all feature flags and their states
    """
    url = get_relative_url("aap_flags_states-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    # check total amount of flags
    assert response.data["count"] == 4
    results = response.data['results']
    found = False
    for result in results:
        if feature_flag_name == result['flag_name']:
            found = True
            assert result['flag_state'] is feature_flag_value
    assert found is True
