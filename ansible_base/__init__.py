try:
    from ._version import __version__, __version_tuple__  # noqa: F401
except Exception:
    import datetime
    import subprocess
    from typing import Tuple, Union

    calver_now = datetime.datetime.now().strftime("%Y.%m.%d")
    shaw = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD']).decode('ascii').strip()

    VERSION_TUPLE = Tuple[Union[int, str], ...]

    __version__: str
    __version_tuple__: VERSION_TUPLE
    version_tuple: VERSION_TUPLE

    __version__ = f'{calver_now}-{shaw}'
    __version_tuple__ = version_tuple = tuple(__version__.split('.'))
