#  Copyright 2024 Red Hat, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

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
