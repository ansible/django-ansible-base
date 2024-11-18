from flags.state import flag_enabled

from ansible_base.lib.utils.settings import get_setting


def get_feature_flags():
    platform_flags = get_setting('FLAGS', {})
    service_flags = get_setting('ANSIBLE_BASE_SERVICE_FEATURE_FLAGS', {})
    platform_flags.update(service_flags)
    response = {}
    all_flags = platform_flags.keys()
    for flag in sorted(all_flags):
        response[flag] = flag_enabled(flag)
    return response
