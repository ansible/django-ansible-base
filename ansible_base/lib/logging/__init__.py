import logging
import threading
from typing import Optional

from ansible_base.lib.utils.settings import get_setting

thread_local = threading.local()

auth_logger = None


def get_auth_logger() -> logging.Logger:
    global auth_logger
    if not auth_logger:
        AUTH_AUDIT_LOGGER_NAME = get_setting('ANSIBLE_BASE_AUTH_AUDIT_LOGGER_NAME', 'ansible_base.auth_audit')
        auth_logger = logging.getLogger(AUTH_AUDIT_LOGGER_NAME)

    return auth_logger


def log_auth_event(message: str, second_logger: Optional[logging.Logger] = None, level: Optional[int] = logging.INFO):
    auth_logger = get_auth_logger()
    auth_logger.log(level, message)
    if second_logger:
        second_logger.log(level, message)


def log_auth_error(message: str, second_logger: Optional[logging.Logger] = None):
    log_auth_event(message, second_logger, logging.ERROR)


def log_auth_warning(message: str, second_logger: Optional[logging.Logger] = None):
    log_auth_event(message, second_logger, logging.WARNING)


def log_auth_exception(message: str, second_logger: Optional[logging.Logger] = None):
    auth_logger = get_auth_logger()
    auth_logger.exception(message)
    if second_logger:
        second_logger.exception(message)
