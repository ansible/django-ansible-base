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

import hashlib
import json
from typing import Callable, Optional, Type

from django.db.models import Model
from rest_framework.serializers import Serializer


def hash_serializer_data(instance: Model, serializer: Type[Serializer], field: Optional[str] = None, hasher: Callable = hashlib.sha256):
    """
    Takes an instance, serialize it and take the .data or the specified field
    as input for the hasher function.
    """
    serialized_data = serializer(instance).data
    if field:
        serialized_data = serialized_data[field]
    metadata_json = json.dumps(serialized_data, sort_keys=True).encode("utf-8")
    return hasher(metadata_json).hexdigest()
