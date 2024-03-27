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

import uuid

from django.db import models


class ServiceID(models.Model):
    """
    Provides a globally unique ID for this service.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, null=False, editable=False)

    def save(self, *args, **kwargs):
        if ServiceID.objects.exists():
            raise RuntimeError("This service already has a ServiceID")

        return super().save()


_service_id = None


def service_id():
    global _service_id
    if not _service_id:
        _service_id = str(ServiceID.objects.first().pk)
    return _service_id
