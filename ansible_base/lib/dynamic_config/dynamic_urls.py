import logging

from django.conf import settings

logger = logging.getLogger('ansible_base.lib.dynamic_config.dynamic_urls')


url_types = ['api_version_urls', 'root_urls', 'api_urls']
for url_type in url_types:
    globals()[url_type] = []

for app in getattr(settings, 'INSTALLED_APPS', []):
    if app.startswith('ansible_base.'):
        try:
            url_module = __import__(f'{app}.urls', fromlist=url_types)
            logger.debug(f'Including URLS from {app}.urls')
            for url_type in ['api_version_urls', 'root_urls', 'api_urls']:
                globals()[url_type].extend(getattr(url_module, url_type, []))
        except ImportError:
            logger.debug(f'Module {app} does not specify urls.py')
