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

from rest_framework import permissions
from rest_framework.viewsets import ReadOnlyModelViewSet

from ansible_base.activitystream.models import Entry
from ansible_base.activitystream.serializers import EntrySerializer
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView


class EntryReadOnlyViewSet(ReadOnlyModelViewSet, AnsibleBaseDjangoAppApiView):
    """
    API endpoint that allows for read-only access to activity stream entries.
    """

    queryset = Entry.objects.all()
    serializer_class = EntrySerializer
    permission_classes = [permissions.IsAuthenticated]
