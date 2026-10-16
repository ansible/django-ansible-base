import subprocess
import sys


def test_filter_extensions_load_without_rbac():
    code = '''
from django.conf import settings

settings.configure(
    INSTALLED_APPS=[
        "django.contrib.contenttypes",
        "ansible_base.rest_filters",
        "ansible_base.api_documentation",
    ],
    SECRET_KEY="test",
)

import django

django.setup()

from ansible_base.api_documentation import filter_extensions

assert not hasattr(filter_extensions, "RoleDefinitionScopeFilterBackendExtension")
'''
    subprocess.run([sys.executable, '-c', code], check=True, capture_output=True, text=True)
