import inspect
import uuid
from typing import Type, Union

from django.apps import apps
from django.conf import settings
from django.db import models
from django.utils.module_loading import import_string

"""
This module has utilities related to processing of remote objects.
Those are, objects that exist on other systems,
but permissions for objects in that system are tracked here.
In this case, the objects do not exist locally,
and the users and teams are assumed to be synchronized.

Even if this feature is not being used, this code will still be used.
Because for consistency, in every case the project name will need to be set.
This module will be the source of truth for things like the projet name.
"""


class StandInPK:
    def __init__(self, ct: models.Model):
        self.pk_field_type = ct.pk_field_type

    def get_prep_value(self, value: Union[str, int, uuid.UUID]) -> Union[str, int]:
        if self.pk_field_type == "uuid":
            if isinstance(value, uuid.UUID):
                return str(value)
            return str(uuid.UUID(value))
        return int(value)

    def to_python(self, value: Union[str, int, uuid.UUID]) -> Union[int, uuid.UUID]:
        if self.pk_field_type == "uuid":
            if isinstance(value, uuid.UUID):
                return value
            return uuid.UUID(value)
        return int(value)

    def django_field(self):
        "This gives a mock Django field like what it mimics"
        if self.pk_field_type == "uuid":
            return models.UUIDField()
        return models.IntegerField()


class StandinMeta:
    def __init__(self, ct: models.Model, abstract=False):
        self.service = ct.service
        self.model_name = ct.model
        self.app_label = ct.app_label
        self.abstract = abstract

        # Provide Django-like labels for error messaging and display
        # e.g., "inventory" -> "inventory" (or title-cased if preferred)
        human_label = self.model_name.replace('_', ' ')
        self.verbose_name = human_label
        self.verbose_name_plural = f"{human_label}s"

        self.pk = StandInPK(ct)


class RemoteObject:
    """Placeholder for objects that live in another project."""

    def __init__(self, content_type: models.Model, object_id: Union[int, str], parent_reference=None):
        self.content_type = content_type
        self.object_id = object_id
        # Since object is remote, we do not have its properties here, so a pointer to the parent can be specified here
        self.parent_reference = parent_reference
        if not hasattr(self, '_meta'):
            # If object is created without a type-specific subclass, do the best we can
            self._meta = StandinMeta(content_type, abstract=True)
        else:
            if content_type.model != self._meta.model_name:
                raise RuntimeError(f'RemoteObject created with type {content_type} but with type for {self._meta.model_name}')

        # Raise an early error if the primary key is obviously not valid for the model type
        try:
            self._meta.pk.to_python(object_id)
        except (ValueError, TypeError, AttributeError) as e:
            raise ValueError(f"Invalid primary key value {object_id} for type {content_type.pk_field_type}, error: {e}")

    def __repr__(self):
        return f"<RemoteObject {self.content_type} id={self.object_id}>"

    def __eq__(self, value):
        if isinstance(value, RemoteObject):
            return bool(self.content_type.id == value.content_type.id and self.pk == value.pk)
        return super().__eq__(value)

    def __hash__(self):
        return hash((self.content_type.id, self.pk))

    @classmethod
    def get_ct_from_type(cls):
        if not hasattr(cls, '_meta'):
            raise ValueError('Generalized RemoteObject can not obtain content_type from its class')
        ct_model = apps.get_model('dab_rbac', 'DABContentType')
        return ct_model.objects.get_by_natural_key(cls._meta.service, cls._meta.app_label, cls._meta.model_name)

    @classmethod
    def access_ids_qs(cls, actor, codename: str = 'view', content_types=None, cast_field=None):
        """Returns a values_list type queryset of ids

        Remote objects do not exist locally, so we can not get a queryset of them,
        but we can still do this, giving a queryset of ids.
        You could use the materialized list to filter API endpoints on the remote server?
        """
        from .evaluations import remote_obj_id_qs

        return remote_obj_id_qs(actor, remote_cls=cls, codename=codename, content_types=content_types, cast_field=cast_field)

    @property
    def pk(self):
        """Alias to :attr:`object_id` for compatibility with Django. Also, handles type."""
        return self._meta.pk.to_python(self.object_id)

    def summary_fields(self):
        """This gives a placeholder, planned to introduce a summary_fields shared endpoint.

        This placeholder should be cleary identifable by a client or by the RBAC resource server.
        Then, the idea, is that it can make a request to the remote server to get the summary data.
        """
        pk_val = self.pk
        if not isinstance(pk_val, int):
            pk_val = str(pk_val)
        return {'<remote_object_placeholder>': True, 'model_name': self._meta.model_name, 'service': self._meta.service, 'pk': pk_val}


def get_remote_base_class() -> Type[RemoteObject]:
    """Return the class which represents remote objects.

    This is for further ORM-level customization of remote object handling.
    More specifically, if you use the DAB RBAC objects, but create your own view.
    This would add properties to the assignment.content_object in the case of remote objects.
    """
    remote_cls = getattr(settings, 'RBAC_REMOTE_OBJECT_CLASS', None)
    if remote_cls:
        return import_string(remote_cls)
    return RemoteObject


def get_resource_registry():
    """Resource registry is another DAB app, and this returns its registry."""
    if 'ansible_base.resource_registry' not in settings.INSTALLED_APPS:
        return None

    # Extremely risky situation around circular imports
    from ansible_base.resource_registry.registry import get_registry

    return get_registry()


def get_local_resource_prefix() -> str:
    """The API project designator for unshared objects local to this service.

    Unless otherwise defined by the resource registry config,
    this is the project field & API prefix that all Django models should set.
    """
    if registry := get_resource_registry():
        return registry.api_config.service_type
    return 'local'


def get_resource_prefix(model: Union[Type[models.Model], models.Model, Type[RemoteObject], RemoteObject]) -> str:
    """The API project designator for given cls, according to the resource registry

    This is used for related slug references, like "awx.inventory" to reference
    The inventory model under the service known as awx.
    """
    if isinstance(model, RemoteObject) or (inspect.isclass(model) and issubclass(model, RemoteObject)):
        # If it is a remote object, it was only ever created from this to begin with
        return model._meta.service

    if registry := get_resource_registry():
        # duplicates logic in ansible_base/resource_registry/apps.py
        try:
            resource_config = registry.get_config_for_model(model)
            if resource_config.managed_serializer:
                return "shared"  # shared model
        except KeyError:
            pass  # unregistered model

        # Fallback for unregistered and non-shared models
        return registry.api_config.service_type
    else:
        return 'local'


_REMOTE_STANDIN_CACHE: dict[tuple[str, str], Type[models.Model]] = {}


def get_remote_standin_class(content_type: models.Model) -> Type:
    """Return a class for a remote model, given its content type."""
    key = (content_type.service, content_type.model)
    standin = _REMOTE_STANDIN_CACHE.get(key)
    if standin is None:
        base = get_remote_base_class()
        name = f"Remote[{content_type.service}:{content_type.app_label}.{content_type.model}]"

        standin = type(
            name,
            (base,),
            {"_meta": StandinMeta(content_type)},
        )
        _REMOTE_STANDIN_CACHE[key] = standin
    return standin
