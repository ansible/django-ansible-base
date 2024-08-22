import logging
from typing import Optional

from django.http import HttpRequest

from ansible_base.jwt_consumer.common.util import validate_x_trusted_proxy_header
from ansible_base.lib.utils.settings import get_setting

logger = logging.getLogger('ansible_base.lib.uitls.requests')


def get_remote_host(request: HttpRequest) -> Optional[str]:
    value = get_remote_hosts(request, get_first_only=True)
    return value[0] if value else None


def split_header(value: str) -> list[str]:
    values = []
    for a_value in value.split(','):
        a_value = a_value.strip()
        if a_value:
            values.append(a_value)
    return values


def get_remote_hosts(request: HttpRequest, get_first_only: bool = False) -> list[str]:
    '''
    Get all IPs from the allowed headers
    NOTE: this function does not unique the hosts to preserve the order of hosts found in the variables
    '''
    remote_hosts = []

    if not request or not hasattr(request, 'META'):
        return remote_hosts

    headers = get_setting('REMOTE_HOST_HEADERS', ['REMOTE_ADDR', 'REMOTE_HOST'])

    for header in headers:
        for value in split_header(request.META.get(header, '')):
            remote_hosts.append(value)

    # If we are connected to from a trusted proxy then we can add some additional headers
    try:
        if 'HTTP_X_TRUSTED_PROXY' in request.META:
            if validate_x_trusted_proxy_header(request.META['HTTP_X_TRUSTED_PROXY']):
                # The last entry in x-forwarded-for from envoy can be trusted implicitly
                # https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_conn_man/headers#x-forwarded-for
                values = split_header(request.META.get('HTTP_X_FORWARDED_FOR', ''))
                if values:
                    remote_hosts.insert(0, values[-1])

                # x-envoy-external-address can always be trusted when coming from envoy
                # https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_conn_man/headers#x-envoy-external-address
                for value in reversed(split_header(request.META.get('HTTP_X_ENVOY_EXTERNAL_ADDRESS', ''))):
                    remote_hosts.insert(0, value)
            else:
                logger.error("Unable to use headers from trusted proxy because shared secret was invalid!")
    except Exception:
        logger.exception("Failed to validate HTTP_X_TRUSTED_PROXY")

    if get_first_only and len(remote_hosts) > 0:
        return [remote_hosts[0]]

    return remote_hosts
