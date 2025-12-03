import logging
import threading
from typing import Optional

from ansible_base.lib.utils.settings import get_setting

thread_local = threading.local()

auth_logger = None


def log_auth_event(message: str, second_logger: Optional[logging.Logger] = None):
    global auth_logger
    if not auth_logger:
        AUTH_AUDIT_LOGGER_NAME = get_setting('ANSIBLE_BASE_AUTH_AUDIT_LOGGER_NAME', 'ansible_base.auth_audit')
        auth_logger = logging.getLogger(AUTH_AUDIT_LOGGER_NAME)

    auth_logger.info(message)
    if second_logger:
        second_logger.info(message)
