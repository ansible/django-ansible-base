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

from collections import namedtuple
from typing import List

ParentResource = namedtuple("ParentResource", ["model", "field_name"])
SharedResource = namedtuple("SharedResource", ["serializer", "is_provider"])


def get_concrete_model(model):
    _model = model
    while _model._meta.proxy_for_model:
        _model = _model._meta.proxy_for_model

    return _model


class ServiceAPIConfig:
    """
    This will be the interface for configuring the resource registry for each service.
    """

    service_type = None


class ResourceConfig:
    model_label = None
    model = None
    externally_managed = None
    managed_serializer = None
    parent_resources = None
    actions = None
    name_field = None

    def __init__(self, model, shared_resource: SharedResource = None, parent_resources: List[ParentResource] = None, name_field: str = None):
        model = get_concrete_model(model)
        self.model_label = model._meta.label

        managed_serializer = None
        externally_managed = False
        if name_field is None:
            name_field = "name"

        if shared_resource:
            managed_serializer = shared_resource.serializer
            externally_managed = not shared_resource.is_provider

        parent_map = {}
        if parent_resources:
            for parent in parent_resources:
                parent_map[parent.model._meta.label] = parent

        self.model = model
        self.externally_managed = externally_managed
        self.managed_serializer = managed_serializer
        self.parent_resources = parent_map
        self.name_field = name_field


class ResourceRegistry:
    registry = {}

    def __init__(self, resource_list: List[ResourceConfig], service_api_config: ServiceAPIConfig = None):
        self._validate_api_config(service_api_config)
        self.api_config = service_api_config
        for r in resource_list:
            self.registry[r.model_label] = r

    def _validate_api_config(self, config):
        """
        Needs to validate that:
            - Viewsets have the correct serializer, pagination and filter classes
            - Service type is set to one of awx, galaxy, eda or aap
        """
        assert config.service_type in ["aap", "awx", "galaxy", "eda"]

    def get_resources(self):
        return self.registry

    def get_config_for_model(self, model=None, model_label=None) -> ResourceConfig:
        if model:
            return self.registry[model._meta.label]
        if model_label:
            return self.registry[model_label]

        raise AttributeError("Must include either model or model_label arg.")


def get_registry() -> ResourceRegistry:
    from django.conf import settings

    if hasattr(settings, "ANSIBLE_BASE_RESOURCE_CONFIG_MODULE"):
        from django.utils.module_loading import import_string

        resource_list = import_string(settings.ANSIBLE_BASE_RESOURCE_CONFIG_MODULE + ".RESOURCE_LIST")
        api_config = import_string(settings.ANSIBLE_BASE_RESOURCE_CONFIG_MODULE + ".APIConfig")

        return ResourceRegistry(resource_list, api_config())
    else:
        return False
