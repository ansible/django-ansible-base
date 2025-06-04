import pytest
from django.conf import settings

from ansible_base.feature_flags.models import AAPFlag
from ansible_base.lib.utils.response import get_relative_url


def test_feature_flags_list_empty_by_default(admin_api_client):
    """
    Test that we can list feature flags api, before preloading data
    """
    url = get_relative_url("aap_flags-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data['results'] == []


def test_feature_flags_list(admin_api_client, aap_flags):
    """
    Test that we can list feature flags api, after preloading data
    """
    url = get_relative_url("aap_flags-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert len(response.data['results']) == 6


@pytest.mark.parametrize(
    'feature_flag, value',
    [
        ('FEATURE_INDIRECT_NODE_COUNTING_ENABLED', True),
        ('FEATURE_POLICY_AS_CODE_ENABLED', True),
        ('FEATURE_EDA_ANALYTICS_ENABLED', False),
        ('FEATURE_GATEWAY_IPV6_USAGE_ENABLED', False),
        ('FEATURE_GATEWAY_CREATE_CRC_SERVICE_TYPE_ENABLED', True),
    ],
)
def test_feature_flags_detail(admin_api_client, feature_flag, value):
    """
    Test that we can list feature flags api, after preloading data
    """
    from ansible_base.feature_flags.utils import create_initial_data

    setattr(settings, feature_flag, value)
    create_initial_data()
    try:
        created_flag = AAPFlag.objects.get(name=feature_flag)
    except AAPFlag.DoesNotExist:
        pytest.fail(f"AAPFlag with name '{feature_flag}' was not found in the database")
    url = get_relative_url("aap_flags-detail", kwargs={'pk': created_flag.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data['name'] == feature_flag
    assert response.data['state'] == value


@pytest.mark.parametrize(
    'flags_list',
    [
        [
            {'name': 'FEATURE_INDIRECT_NODE_COUNTING_ENABLED', 'value': True},
            {'name': 'FEATURE_POLICY_AS_CODE_ENABLED', 'value': True},
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

    for flag in flags_list:
        setattr(settings, flag['name'], flag['value'])
    expected_flag_states = {item['name']: item['value'] for item in flags_list}

    create_initial_data()
    url = get_relative_url("aap_flags_states-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert len(response.data['results']) == 6

    found_and_verified_flags_count = 0
    for flag_from_api in response.data['results']:
        api_flag_name = flag_from_api.get('flag_name')
        if api_flag_name in expected_flag_states:
            found_and_verified_flags_count += 1
            expected_value = expected_flag_states[api_flag_name]
            actual_value = flag_from_api.get('flag_state')
            assert actual_value == expected_value

    # Assert that all flags you intended to check were actually found in the API response and verified
    assert found_and_verified_flags_count == len(expected_flag_states)


def test_old_feature_flags_list(admin_api_client, aap_flags):
    """
    Test that we can list feature flags api, after preloading data
    """
    url = get_relative_url("featureflags-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert len(response.data) == 6
