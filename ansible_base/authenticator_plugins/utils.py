import logging
from glob import glob
from os.path import basename, isfile, join

from django.conf import settings

logger = logging.getLogger('ansible_base.authenticator_plugins.utils')
setting = 'ANSIBLE_BASE_AUTHENTICATOR_CLASS_PREFIX'


def get_authenticator_plugins() -> list:
    class_prefix = getattr(settings, setting, None)
    parent_class = __import__(class_prefix, globals(), locals(), ['authenticator_plugins'], 0)
    plugins = []
    for path in parent_class.__path__:
        for file in glob(join(path, "*.py")):
            file_name = basename(file)
            if isfile(file) and file_name not in ['__init__.py', 'utils.py', 'base.py']:
                plugins.append(file_name.replace('.py', ''))
    return plugins


def get_authenticator_class(authenticator_type: str):
    if not authenticator_type:
        raise ImportError("Must pass authenticator type to import")
    class_prefix = getattr(settings, setting, None)
    if not class_prefix:
        raise ImportError(f'{setting} was not properly set for dynamic import')
    try:
        class_name = f'{class_prefix}.{authenticator_type}'
        logger.debug(f"Attempting to load class {class_name}")
        auth_class = __import__(class_name, globals(), locals(), ['AuthenticatorPlugin'], 0)
        return auth_class.AuthenticatorPlugin
    except ImportError as e:
        logger.exception(f"The specified authenticator type {authenticator_type} could not be loaded")
        raise ImportError(f"The specified authenticator type {authenticator_type} could not be loaded") from e


def get_authenticator_plugin(authenticator_type: str):
    AuthClass = get_authenticator_class(authenticator_type)
    return AuthClass()
