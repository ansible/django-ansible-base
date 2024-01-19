import importlib
import logging
from typing import Any

from django.conf import settings

logger = logging.getLogger('ansible_base.lib.utils.settings')


class SettingNotSetException(Exception):
    pass


def get_setting(name: str, default: Any = None) -> Any:
    settings_function = getattr(settings, 'ANSIBLE_BASE_SETTINGS_FUNCTION', None)
    if settings_function:
        try:
            module_name, _, function_name = settings_function.rpartition('.')
            the_function = getattr(importlib.import_module(module_name), function_name)
            setting = the_function(name)
            return setting
        except SettingNotSetException:
            # If the setting was not set thats ok, we will fall through to trying to get it from the django setting or the default value
            pass
        except Exception:
            logger.exception(
                'ANSIBLE_BASE_SETTINGS_FUNCTION was set but calling it as a function failed (see exception), '
                'ignoring error and attempting to load from settings'
            )

    return getattr(settings, name, default)
