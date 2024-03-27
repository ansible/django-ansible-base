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

from django.urls import re_path

from ansible_base.jwt_consumer.apps import JwtConsumerConfig
from ansible_base.jwt_consumer.views import PlatformUIRedirectView

logger = logging.getLogger('ansible_base.jwt_consumer.urls')

# This is a special case because the application has to include this in a very specific location
# in order for the redirect to be picked up.
# Therefore we will not add it to our standard api_urls/api_root_urls/root_url variables.

app_name = JwtConsumerConfig.label
urlpatterns = [
    re_path(r'', PlatformUIRedirectView.as_view()),
]
