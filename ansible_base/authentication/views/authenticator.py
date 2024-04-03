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

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from ansible_base.authentication.models import Authenticator, AuthenticatorUser
from ansible_base.authentication.serializers import AuthenticatorSerializer
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView

logger = logging.getLogger('ansible_base.authentication.views.authenticator')


class AuthenticatorViewSet(AnsibleBaseDjangoAppApiView, ModelViewSet):
    """
    API endpoint that allows authenticators to be viewed or edited.
    """

    queryset = Authenticator.objects.all()
    serializer_class = AuthenticatorSerializer
    permission_classes = [permissions.IsAuthenticated]

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        users_exist = AuthenticatorUser.objects.filter(provider_id=instance.slug).exists()
        if users_exist:
            logger.info("Found existing users from the authenticator")
            return Response(
                status=status.HTTP_409_CONFLICT, data={"details": "Authenticator cannot be deleted, as users from the authenticator exist in the system"}
            )
        else:
            logger.info(f"Deleting authenticator with ID={instance.id}")
            return super().destroy(request, *args, **kwargs)
