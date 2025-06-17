import pytest
from django.conf import settings
from flags.state import disable_flag, enable_flag, flag_state

from ansible_base.feature_flags.models import AAPFlag
from ansible_base.feature_flags.utils import feature_flags_list


@pytest.mark.django_db
def test_total_platform_flags(aap_flags):
    assert AAPFlag.objects.count() == len(feature_flags_list())


@pytest.mark.django_db
@pytest.mark.parametrize(
    "feature_flag",
    feature_flags_list(),
)
def test_feature_flags_from_db(aap_flags, feature_flag):
    flag = AAPFlag.objects.get(name=feature_flag['name'])
    assert flag
    assert feature_flag.get('ui_name') == flag.ui_name
    assert feature_flag.get('condition') == flag.condition
    assert feature_flag.get('visibility') == flag.visibility
    assert feature_flag.get('value') == flag.value
    assert feature_flag.get('support_level') == flag.support_level
    assert feature_flag.get('description') == flag.description
    assert feature_flag.get('support_url') == flag.support_url
    assert feature_flag.get('labels') == flag.labels
    assert feature_flag.get('required', False) == flag.required
    assert feature_flag.get('toggle_type', 'run-time') == flag.toggle_type


@pytest.mark.django_db
@pytest.mark.parametrize(
    "feature_flag, value",
    [
        ('FEATURE_INDIRECT_NODE_COUNTING_ENABLED', True),
        ('FEATURE_GATEWAY_IPV6_USAGE_ENABLED', False),
    ],
)
def test_feature_flag_database_setting_override(feature_flag, value):
    AAPFlag.objects.all().delete()
    from ansible_base.feature_flags.utils import create_initial_data

    setattr(settings, feature_flag, value)
    create_initial_data()
    flag = AAPFlag.objects.get(name=feature_flag)
    assert flag.value == str(value)


@pytest.mark.django_db
def test_enable_and_disable_flag_functions(aap_flags):
    flag_name = "FEATURE_INDIRECT_NODE_COUNTING_ENABLED"
    # Assert Initial State
    assert flag_state(flag_name) is False

    # Ensure flag can be enabled via django-flags enable_flag function
    enable_flag(flag_name)
    assert flag_state(flag_name) is True
    # Ensure flag can be disabled via django-flags enable_flag function
    disable_flag(flag_name)
    assert flag_state(flag_name) is False
