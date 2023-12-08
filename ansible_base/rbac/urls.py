from django.urls import include, path

from ansible_base.rbac.api.router import router
from ansible_base.rbac.apps import AnsibleRBACConfig

app_name = AnsibleRBACConfig.label

api_version_urls = [
    path('', include(router.urls)),
]

root_urls = []

api_urls = []
