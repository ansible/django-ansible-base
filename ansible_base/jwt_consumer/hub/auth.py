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

from ansible_base.jwt_consumer.common.auth import JWTAuthentication
from ansible_base.jwt_consumer.common.exceptions import InvalidService


class HubJWTAuth(JWTAuthentication):
    def process_permissions(self, user, claims, token):
        # Map teams in the JWT to Automation Hub groups.
        try:
            from galaxy_ng.app.models.auth import Group
        except ImportError:
            raise InvalidService("automation-hub")

        for team in claims.get("teams", []):
            hub_group, _ = Group.objects.get_or_create(name=team["name"])
            hub_group.user_set.add(user)
