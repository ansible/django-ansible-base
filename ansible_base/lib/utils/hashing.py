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
