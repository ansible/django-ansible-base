try:
    from ._version import version
except ImportError:
    version = '0.0.0.dev'

from typing import Tuple, Union

VERSION_TUPLE = Tuple[Union[int, str], ...]

__version__: str
__version_tuple__: VERSION_TUPLE
version_tuple: VERSION_TUPLE

__version__ = version
__version_tuple__ = version_tuple = tuple(version.split('.'))
