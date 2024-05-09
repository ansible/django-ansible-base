import logging
from typing import Optional

from django.http import HttpRequest

from ansible_base.lib.utils.encryption import SharedSecretNotFound, validate_hmac_sha256_shared_secret
from ansible_base.lib.utils.settings import get_setting

logger = logging.getLogger('ansible_base.lib.uitls.requests')


def get_remote_host(request: HttpRequest) -> Optional[str]:
    value = get_remote_hosts(request, get_first_only=True)
    return value[0] if value else None


def get_remote_hosts(request: HttpRequest, get_first_only: bool = False) -> list[str]:
    '''
    Get all IPs from the allowed headers
    NOTE: this function does not unique the hosts to preserve the order of hosts found in the variables
    '''
    remote_hosts = []

    if not request or not hasattr(request, 'META'):
        return remote_hosts

    headers = get_setting('REMOTE_HOST_HEADERS', ['REMOTE_ADDR', 'REMOTE_HOST'])

    # If we are connected to from a trusted proxy then we can add some additional headers
    try:
        if 'HTTP_X_TRUSTED_PROXY' in request.META:
            if validate_hmac_sha256_shared_secret(request.META['HTTP_X_TRUSTED_PROXY']):
                headers.insert(0, 'HTTP_X_FORWARDED_FOR')
                headers.insert(0, 'HTTP_X_ENVOY_EXTERNAL_ADDRESS')
            else:
                logger.error("Unable to use headers from trusted proxy because shared secret was invalid!")
    except SharedSecretNotFound:
        logger.warning("Unable to use headers from trusted proxy because the shared secret was not set.")
    except Exception:
        logger.exception("Failed to validate HTTP_X_TRUSTED_PROXY")

    for header in headers:
        for value in request.META.get(header, '').split(','):
            value = value.strip()
            if value:
                if get_first_only:
                    return [value]
                remote_hosts.append(value)
    return remote_hosts
