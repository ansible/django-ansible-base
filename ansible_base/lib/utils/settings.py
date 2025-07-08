import importlib
import logging
from typing import Any

from django.conf import settings
from django.utils.translation import gettext_lazy as _

from ansible_base.lib.utils.validation import to_python_boolean

logger = logging.getLogger('ansible_base.lib.utils.settings')


class SettingNotSetException(Exception):
    pass


def get_setting(name: str, default: Any = None, log_exception: bool = True) -> Any:
    try:
        the_function = get_function_from_setting('ANSIBLE_BASE_SETTINGS_FUNCTION')
        if the_function:
            setting = the_function(name)
            return setting
    except SettingNotSetException:
        # If the setting was not set thats ok, we will fall through to trying to get it from the django setting or the default value
        pass
    except Exception:
        if log_exception:
            logger.exception(
                _(
                    'ANSIBLE_BASE_SETTINGS_FUNCTION was set but calling it as a function failed (see exception), '
                    'ignoring error and attempting to load from settings'
                )
            )

    return getattr(settings, name, default)


def get_function_from_setting(setting_name: str) -> Any:
    setting = getattr(settings, setting_name, None)
    if not setting:
        return None

    try:
        module_name, _junk, function_name = setting.rpartition('.')
        the_function = getattr(importlib.import_module(module_name), function_name)
        return the_function
    except Exception:
        logger.exception(_('{setting_name} was set but we were unable to import its reference as a function.').format(setting_name=setting_name))
        return None


def replace_trusted_origins(func):
    """Decorator for patching the CSRF_TRUSTED_ORIGINS django setting using the potentially different value in get_setting for the duration of a
    function call
    """

    def override_setting(*args, **kwargs):
        csrf_trusted_origins = settings.CSRF_TRUSTED_ORIGINS
        try:
            # Temporarily patch the setting
            settings.CSRF_TRUSTED_ORIGINS = get_setting("CSRF_TRUSTED_ORIGINS", csrf_trusted_origins)
            return func(*args, **kwargs)
        finally:
            # Revert setting after this is done
            settings.CSRF_TRUSTED_ORIGINS = csrf_trusted_origins

    return override_setting


def get_from_import(module_name, attr):
    "Thin wrapper around importlib.import_module, mostly exists so that we can safely mock this in tests"
    module = importlib.import_module(module_name, package=attr)
    return getattr(module, attr)


def is_aoc_instance():
    managed_cloud_setting = 'ANSIBLE_BASE_MANAGED_CLOUD_INSTALL'
    try:
        return to_python_boolean(getattr(settings, managed_cloud_setting, False))
    except ValueError:
        logger.error(f'{managed_cloud_setting} was set but could not be converted to a boolean, assuming false')
        return False
