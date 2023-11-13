from rest_framework.schemas.generators import BaseSchemaGenerator

from collections import namedtuple

ChildResource = namedtuple("ChildResource", ["model", "field_name"])


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
    resource_graph = {}
    child_nodes = set()

    def __init__(self, urlpatterns=None):
        self.resource_inspector = ResourceInspector(urlpatterns=urlpatterns)

    def get_root_resources(self):
        return set(self.registry.keys()) - self.child_nodes

    def get_all_children(self, model_label):
        children = set()

        if model_label in self.resource_graph:
            children = self.resource_graph[model_label]
            for child in self.resource_graph[model_label]:
                children = children.union(self.get_all_children(child))

        return children

    def get_parents(self, model_label):
        parents = set()
        for label, children in self.resource_graph.items():
            if model_label in children:
                parents.add(label)
        return parents

    # TODO: For external types, provide a library of extensible serializers that
    # each service can integrate + list of external types
    def register(self, model, externally_managed=False, managed_serializer=None, child_resources=None):
        model_label = model._meta.label

        if child_resources and len(child_resources) > 0:
            self.resource_graph[model_label] = set()
            for child in child_resources:
                child_label = child["model"]._meta.label
                self.child_nodes.add(child_label)
                # validate that there aren't any cycles
                if child_label in self.resource_graph:
                    if model_label == child_label or model_label in self.get_all_children(child_label):
                        msg = f"Circular resource detected: {model_label}"
                        raise AssertionError(msg)

                self.resource_graph[model_label].add(child_label)

        child_map = {}
        if child_resources:
            for child in child_resources:
                child_map[child["model"]._meta.label] = child

        self.registry[model_label] = {
            "model": model,
            "externally_managed": externally_managed,
            "managed_serializer": managed_serializer,
            "child_resources": child_map,
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
