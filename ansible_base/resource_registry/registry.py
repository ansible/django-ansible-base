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


class ResourceInspector:
    def __init__(self, urlpatterns=None):
        from rest_framework.schemas.generators import BaseSchemaGenerator

        schema_generator = BaseSchemaGenerator()

        schema_generator._initialise_endpoints()
        self.model_map = {}

        for path, method, callback in schema_generator.endpoints:
            view = schema_generator.create_view(callback, method)

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
                except:  # noqa E722
                    pass


class ResourceConfig:
    model_label = None
    model = None
    externally_managed = None
    managed_serializer = None
    parent_resources = None
    actions = None
    name_field = None

    def __init__(self, model, shared_resource: SharedResource = None, parent_resources: List[ParentResource] = None, name_field: str = None):
        if not hasattr(self, 'service_type'):
            from django.conf import settings  # delay import until use to reduce chance of circular imports

            self.service_type = settings.ANSIBLE_BASE_SERVICE_PREFIX

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
        self.actions = ResourceInspector().model_map.get(self.model_label, {})
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
