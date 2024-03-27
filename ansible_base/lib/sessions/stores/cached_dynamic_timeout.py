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

from django.contrib.sessions.backends.cached_db import SessionStore as CachedDBSessionStore
from django.utils.translation import gettext_lazy as _

from ansible_base.lib.utils.settings import get_setting

DEFAULT_SESSION_TIMEOUT = 30 * 60
logger = logging.getLogger('ansible_base.lib.sessions.stores.cached_dynamic_timeout')


class SessionStore(CachedDBSessionStore):
    cache_key_prefix = 'ansible_base.lib.sessions.stores.cached_dynamic_timeout'

    def get_session_cookie_age(self):
        timeout = get_setting('SESSION_COOKIE_AGE', DEFAULT_SESSION_TIMEOUT)
        if not isinstance(timeout, int):
            logger.error(
                _('SESSION_COOKIE_AGE was set to %(timeout)s which is an invalid int, defaulting to %(default)s')
                % {'timeout': timeout, 'default': DEFAULT_SESSION_TIMEOUT}
            )
            timeout = DEFAULT_SESSION_TIMEOUT
        return timeout
