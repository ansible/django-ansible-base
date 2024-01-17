import logging

from django.conf import settings
from django.urls import include, path

logger = logging.getLogger('ansible_base.urls')

list_actions = {'get': 'list', 'post': 'create'}
detail_actions = {'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}
view_only_list = {'get': 'list'}

urlpatterns = []

for app in getattr(settings, 'INSTALLED_APPS', []):
    if app.startswith('ansible_base.'):
        logger.info(f'Including URLS from {app}.urls')
        urlpatterns.append(path('', include(f'{app}.urls')))
