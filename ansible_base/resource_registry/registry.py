from collections import namedtuple

from rest_framework import permissions
from rest_framework.schemas.generators import BaseSchemaGenerator

ChildResource = namedtuple("ChildResource", ["model", "field_name"])


class ServiceAPIConfig:
    service_type = None

    role_definitions_viewset = None
    user_role_assignment_viewset = None
    team_role_assignment_viewset = None
    permission_viewset = None

    permission_class = permissions.IsAuthenticated

    def authorize_user(username, password=None, ansible_id=None):
        raise NotImplementedError


class ResourceInspector(BaseSchemaGenerator):
    def __init__(self, urlpatterns=None):
        super().__init__(patterns=urlpatterns)

        self._initialise_endpoints()
        self.model_map = {}

        for path, method, callback in self.endpoints:
            view = self.create_view(callback, method)

            if hasattr(view, "get_serializer_class"):
                serializer_class = view.get_serializer_class()
                if hasattr(serializer_class, "Meta"):
                    label = serializer_class.Meta.model._meta.label
                    if label not in self.model_map:
                        self.model_map[label] = {}

                    if hasattr(view, "action"):
                        action = view.action
                        if action == "partial_update":
                            action = "update"
                        if action not in self.model_map[label]:
                            self.model_map[label][action] = []
                        self.model_map[label][action].append((method, path))


class ResourceRegistry:
    registry = {}

    def __init__(self, service_api_config: ServiceAPIConfig = None, urlpatterns=None):
        self.resource_inspector = ResourceInspector(urlpatterns=urlpatterns)

        self._validate_api_config(service_api_config)
        self.api_config = service_api_config

    def _validate_api_config(self, config):
        """
        Needs to validate that:
            - Viewsets have the correct serializer, pagination and filter classes
            - Service type is set to one of awx, galaxy, eda or gateway
        """
        pass

    def register(self, model, externally_managed=False, managed_serializer=None, parent_resources=None):
        model_label = model._meta.label

        parent_map = {}
        if parent_resources:
            for parent in parent_resources:
                parent_map[parent["model"]._meta.label] = parent

        self.registry[model_label] = {
            "model": model,
            "externally_managed": externally_managed,
            "managed_serializer": managed_serializer,
            "child_resources": parent_map,
            "actions": self.resource_inspector.model_map.get(model_label),
        }

    def get_resources(self):
        return self.registry

    def get_config_for_model(self, model=None, model_label=None):
        if model:
            return self.registry[model._meta.label]
        if model_label:
            return self.registry[model_label]

        raise AttributeError("Must include either model or model_label arg.")

    def get_urls(self):
        # remove calls for gateway managed resources
        return self.resource_inspector.patterns
