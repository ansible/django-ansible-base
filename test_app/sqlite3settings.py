"""
This is kept for backwards compatibility with deployments settings
DJANGO_SETTINGS_MODULE to test_app.sqlite3settings
"""

from ansible_base.lib.dynamic_config import export

from .settings import DYNACONF

DYNACONF.load_file("sqlite_defaults.py")
export(__name__, DYNACONF)
