from typing import Tuple, Union

VERSION_TUPLE = Tuple[Union[int, str], ...]

version: str
__version__: str
__version_tuple__: VERSION_TUPLE
version_tuple: VERSION_TUPLE

__version__ = version = '0.0.0.dev'
__version_tuple__ = version_tuple = tuple(version.split('.'))
