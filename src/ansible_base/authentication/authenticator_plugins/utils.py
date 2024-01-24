import logging
from glob import glob
from os.path import basename, isfile, join

from django.conf import settings
from django.utils.text import slugify

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.utils')
setting = 'ANSIBLE_BASE_AUTHENTICATOR_CLASS_PREFIXES'


def get_authenticator_plugins() -> list:
    class_prefixes = getattr(settings, setting, [])
    plugins = []
    for class_prefix in class_prefixes:
        path_info = class_prefix.split('.')
        last_class_path = path_info[-1]
        parent_class = __import__(class_prefix, globals(), locals(), [last_class_path], 0)
        for path in parent_class.__path__:
            for file in glob(join(path, "*.py")):
                file_name = basename(file)
                if isfile(file) and file_name not in ['__init__.py', 'utils.py', 'base.py']:
                    plugins.append(f"{class_prefix}.{file_name.replace('.py', '')}")
    return plugins


def get_authenticator_class(authenticator_type: str):
    if not authenticator_type:
        raise ImportError("Must pass authenticator type to import")
    try:
        logger.debug(f"Attempting to load class {authenticator_type}")
        auth_class = __import__(authenticator_type, globals(), locals(), ['AuthenticatorPlugin'], 0)
        return auth_class.AuthenticatorPlugin
    except Exception as e:
        logger.exception(f"The specified authenticator type {authenticator_type} could not be loaded")
        raise ImportError(f"The specified authenticator type {authenticator_type} could not be loaded") from e


def get_authenticator_plugin(authenticator_type: str):
    AuthClass = get_authenticator_class(authenticator_type)
    return AuthClass()


def get_authenticator_urls(authenticator_type: str) -> list:
    try:
        urls = __import__(authenticator_type, globals(), locals(), ['urls'], 0)
        return urls
    except Exception as e:
        logger.error(f"Failed to load urls form {authenticator_type} {e}")
    return None


def generate_authenticator_slug(type: str, name: str) -> str:
    return slugify(f"{type.replace('.', ' ')}__{name}")
