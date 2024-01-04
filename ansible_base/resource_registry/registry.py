from collections import namedtuple
from typing import List

from rest_framework import permissions
from rest_framework.schemas.generators import BaseSchemaGenerator

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


class ResourceInspector(BaseSchemaGenerator):
    def __init__(self, urlpatterns=None):
        super().__init__(patterns=urlpatterns)

        self._initialise_endpoints()
        self.model_map = {}

        for path, method, callback in self.endpoints:
            view = self.create_view(callback, method)

            if hasattr(view, "get_serializer_class"):
                try:
                    serializer_class = view.get_serializer_class()
                    if hasattr(serializer_class, "Meta"):
                        model = get_concrete_model(serializer_class.Meta.model)
                        label = model._meta.label
                        if label not in self.model_map:
                            self.model_map[label] = {}

                        if hasattr(view, "action"):
                            action = view.action
                            if action == "partial_update":
                                action = "update"
                            if action not in self.model_map[label]:
                                self.model_map[label][action] = []
                            self.model_map[label][action].append((method, path))
                except:
                    pass


class ResourceRegistry:
    registry = {}

    def __init__(self, service_api_config: ServiceAPIConfig = None):
        self.resource_inspector = ResourceInspector()

        self._validate_api_config(service_api_config)
        self.api_config = service_api_config

    def _validate_api_config(self, config):
        """
        Needs to validate that:
            - Viewsets have the correct serializer, pagination and filter classes
            - Service type is set to one of awx, galaxy, eda or gateway
        """
        assert config.service_type in ["aap", "awx", "galaxy", "eda"]

    def register(self, model, shared_resource: SharedResource = None, parent_resources: List[ParentResource] = None, name_field: str = None):
        model = get_concrete_model(model)
        model_label = model._meta.label

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

        self.registry[model_label] = {
            "model": model,
            "externally_managed": externally_managed,
            "managed_serializer": managed_serializer,
            "parent_resources": parent_map,
            "actions": self.resource_inspector.model_map.get(model_label, {}),
            "name_field": name_field,
        }

    def get_resources(self):
        return self.registry

    def get_config_for_model(self, model=None, model_label=None):
        if model:
            return self.registry[model._meta.label]
        if model_label:
            return self.registry[model_label]

        raise AttributeError("Must include either model or model_label arg.")
