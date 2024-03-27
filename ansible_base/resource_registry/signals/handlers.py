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

from functools import lru_cache

from ansible_base.resource_registry.models import Resource, init_resource_from_object
from ansible_base.resource_registry.registry import get_registry


@lru_cache(maxsize=1)
def get_resource_models():
    resource_models = set()
    registry = get_registry()
    if registry:
        for k, resource in registry.get_resources().items():
            resource_models.add(resource.model)

    return resource_models


def remove_resource(sender, instance, **kwargs):
    try:
        resource = Resource.get_resource_for_object(instance)
        resource.delete()
    except Resource.DoesNotExist:
        return


def update_resource(sender, instance, created, **kwargs):
    try:
        resource = Resource.get_resource_for_object(instance)
        resource.update_from_content_object()
    except Resource.DoesNotExist:
        resource = init_resource_from_object(instance)
        resource.save()
