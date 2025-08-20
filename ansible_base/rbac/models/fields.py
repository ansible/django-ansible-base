from django.contrib.contenttypes.fields import GenericForeignKey as DjangoGenericForeignKey
from django.core import checks
from django.core.exceptions import FieldDoesNotExist, ObjectDoesNotExist
from django.db import models

from ..remote import RemoteObject, get_local_resource_prefix
from .content_type import DABContentType


class FederatedForeignKey(DjangoGenericForeignKey):
    """A GenericForeignKey variant aware of service boundaries."""

    def __init__(
        self,
        ct_field="content_type",
        fk_field="object_id",
        for_concrete_model=True,
    ):
        super().__init__(ct_field=ct_field, fk_field=fk_field, for_concrete_model=for_concrete_model)

    def _check_content_type_field(self):
        try:
            field = self.model._meta.get_field(self.ct_field)
        except FieldDoesNotExist:
            return [
                checks.Error(
                    "The GenericForeignKey content type references the nonexistent field '%s.%s'." % (self.model._meta.object_name, self.ct_field),
                    obj=self,
                    id="contenttypes.E002",
                )
            ]
        else:
            if not isinstance(field, models.ForeignKey):
                return [
                    checks.Error(
                        "'%s.%s' is not a ForeignKey." % (self.model._meta.object_name, self.ct_field),
                        hint=("GenericForeignKeys must use a ForeignKey to 'federated_foreign_key.DABContentType' as the 'content_type' field."),
                        obj=self,
                        id="contenttypes.E003",
                    )
                ]
            elif field.remote_field.model != DABContentType:
                return [
                    checks.Error(
                        "'%s.%s' is not a ForeignKey to 'federated_foreign_key.DABContentType'." % (self.model._meta.object_name, self.ct_field),
                        hint=("GenericForeignKeys must use a ForeignKey to 'federated_foreign_key.DABContentType' as the 'content_type' field."),
                        obj=self,
                        id="contenttypes.E004",
                    )
                ]
            else:
                return []

    def get_content_type(self, obj=None, id=None, using=None, model=None):
        if obj is not None:
            if isinstance(obj, RemoteObject):
                return obj.content_type
            return DABContentType.objects.db_manager(obj._state.db).get_for_model(
                obj.__class__,
            )
        elif id is not None:
            return DABContentType.objects.db_manager(using).get_for_id(id)
        elif model is not None:
            return DABContentType.objects.db_manager(using).get_for_model(model)
        else:
            raise RuntimeError("Impossible arguments to get_content_type")

    def __get__(self, instance, cls=None):
        if instance is None:
            return self

        ct_id, pk_val = self._get_field_values(instance)
        rel_obj = self.get_cached_value(instance, default=None)

        if self._should_use_cached_object(instance, rel_obj, ct_id):
            return rel_obj

        if self._is_cached_object_valid(rel_obj, ct_id, pk_val):
            return rel_obj

        rel_obj = self._fetch_related_object(ct_id, pk_val)
        self.set_cached_value(instance, rel_obj)
        return rel_obj

    def _get_field_values(self, instance):
        """Extract content type ID and primary key values from instance."""
        f = instance._meta.get_field(self.ct_field)
        ct_id = getattr(instance, f.attname, None)
        pk_val = getattr(instance, self.fk_field)
        return ct_id, pk_val

    def _should_use_cached_object(self, instance, rel_obj, ct_id):
        """Check if we should return the cached object (even if None)."""
        if rel_obj is not None or not self.is_cached(instance):
            return False

        # Handle prefetch_related cache issue for remote objects
        if ct_id is not None:
            ct = self.get_content_type(id=ct_id)
            local_prefix = get_local_resource_prefix()
            if ct.service not in (local_prefix, "shared"):
                # Remote object incorrectly cached as None - don't use cache
                return False

        # Local/shared object genuinely None or no content type
        return True

    def _is_cached_object_valid(self, rel_obj, ct_id, pk_val):
        """Check if the cached object matches the current field values."""
        if rel_obj is None:
            return False

        ct_match = ct_id == self.get_content_type(obj=rel_obj).id
        pk_match = ct_match and str(rel_obj.pk) == str(pk_val)
        return pk_match

    def _fetch_related_object(self, ct_id, pk_val):
        """Fetch the related object from database or create remote object."""
        if ct_id is None:
            return None

        ct = self.get_content_type(id=ct_id)
        local_prefix = get_local_resource_prefix()
        if ct.service == local_prefix or ct.service == "shared":
            return self._fetch_local_object(ct, pk_val)
        else:
            return ct.get_object_for_this_type(pk=pk_val)

    def _fetch_local_object(self, ct, pk_val):
        """Fetch local/shared object with exception handling."""
        try:
            return ct.get_object_for_this_type(pk=pk_val)
        except (ObjectDoesNotExist, LookupError):
            return None
