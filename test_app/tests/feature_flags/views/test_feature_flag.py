import pytest
from django.conf import settings

from ansible_base.feature_flags.models import AAPFlag
from ansible_base.feature_flags.utils import feature_flags_list
from ansible_base.lib.utils.response import get_relative_url


@pytest.mark.parametrize(
    'flags_list',
    [
        [
            {'name': 'FEATURE_INDIRECT_NODE_COUNTING_ENABLED', 'value': True},
            {'name': 'FEATURE_EDA_ANALYTICS_ENABLED', 'value': True},
        ],
        [
            {'name': 'FEATURE_GATEWAY_IPV6_USAGE_ENABLED', 'value': False},
            {'name': 'FEATURE_GATEWAY_CREATE_CRC_SERVICE_TYPE_ENABLED', 'value': True},
        ],
    ],
)
def test_feature_flags_states_list(admin_api_client, flags_list):
    """
    Test that we can list feature flags api, after preloading data
    """
    from ansible_base.feature_flags.utils import create_initial_data

    AAPFlag.objects.all().delete()
    for flag in flags_list:
        setattr(settings, flag['name'], flag['value'])
    expected_flag_states = {item['name']: item['value'] for item in flags_list}

    create_initial_data()
    url = get_relative_url("aap_flags_states-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert len(response.data['results']) == len(feature_flags_list())

    found_and_verified_flags_count = 0
    for flag_from_api in response.data['results']:
        api_flag_name = flag_from_api.get('name')
        if api_flag_name in expected_flag_states:
            found_and_verified_flags_count += 1
            expected_value = expected_flag_states[api_flag_name]
            actual_value = flag_from_api.get('state')
            assert actual_value == expected_value

    # Assert that all flags you intended to check were actually found in the API response and verified
    assert found_and_verified_flags_count == len(expected_flag_states)


def test_old_feature_flags_list(admin_api_client, aap_flags):
    """
    Test that we can list feature flags api, after preloading data
    """
    url = get_relative_url("feature-flags-state-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert len(response.data) == len(feature_flags_list())
