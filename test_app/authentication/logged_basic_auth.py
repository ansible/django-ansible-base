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

from django.utils.encoding import smart_str
from rest_framework import authentication

logger = logging.getLogger('test_app.authentication.logged_basic_auth')


class LoggedBasicAuthentication(authentication.BasicAuthentication):
    def authenticate(self, request):
        ret = super(LoggedBasicAuthentication, self).authenticate(request)
        if ret:
            username = ret[0].username if ret[0] else '<none>'
            logger.info(smart_str(f"User {username} performed a {request.method} to {request.path} through the API via basic auth"))
        return ret

    def authenticate_header(self, request):
        return super(LoggedBasicAuthentication, self).authenticate_header(request)


# NOTE: This file is common to many of the services and will allow DRF to return a 401 instead of a 403 on failed login.
#       This is the expected behavior we want so we need this file in test_app to mimic other applications
