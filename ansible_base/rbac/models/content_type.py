import inspect
from collections import defaultdict
from typing import Any, Dict, Optional, Sequence, Tuple, Type, Union

from django.apps import apps
from django.db import models as django_models
from django.db.models import Max
from django.db.models.options import Options
from django.utils.translation import gettext_lazy as _

from ..remote import RemoteObject, get_local_resource_prefix, get_resource_prefix


class DABContentTypeManager(django_models.Manager[django_models.Model]):
    """Manager storing DABContentType objects in a local cache like original ContentType.

    The major structural difference is that the cache keys have to add the service reference.
    """

    use_in_migrations = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._cache: Dict[str, Dict[Union[Tuple[str, str, str], int], django_models.Model]] = {}

    def clear_cache(self) -> None:
        self._cache.clear()

    def create(self, *args: Any, **kwargs: Any) -> django_models.Model:
        obj = super().create(*args, **kwargs)
        self._add_to_cache(self.db, obj)
        return obj

    def _add_to_cache(self, using: str, ct: django_models.Model) -> None:
        """Store ``ct`` in the manager cache for the given database alias."""
        key = (ct.service, ct.app_label, ct.model)
        self._cache.setdefault(using, {})[key] = ct
        self._cache.setdefault(using, {})[ct.id] = ct

    def _get_from_cache(self, opts: Options, service: str) -> django_models.Model:
        """Return a cached ``DABContentType`` for ``opts`` and ``service``."""
        key = (service, opts.app_label, opts.model_name)
        return self._cache[self.db][key]  # type: ignore[index]

    def _get_opts(self, model: Union[Type[django_models.Model], django_models.Model], for_concrete_model: bool) -> Options:
        """Return the ``Options`` object for ``model``."""
        return model._meta.concrete_model._meta if for_concrete_model else model._meta

    def get_for_model(
        self,
        model: Union[Type[django_models.Model], django_models.Model, RemoteObject, Type[RemoteObject]],
        for_concrete_model: bool = True,
        service: Optional[str] = None,
    ) -> django_models.Model:
        # Is a remote object, we only know of these objects by virtue of their content type
        if isinstance(model, RemoteObject):
            ct = model.content_type
            self._add_to_cache(self.db, ct)
            return ct
        elif inspect.isclass(model) and issubclass(model, RemoteObject):
            ct = self.get_by_natural_key(model._meta.service, model._meta.app_label, model._meta.model_name)
            self._add_to_cache(self.db, ct)
            return ct

        if service is None:
            query_service = get_resource_prefix(model)
        else:
            query_service = service

        opts = self._get_opts(model, for_concrete_model)
        try:
            return self._get_from_cache(opts, query_service)
        except KeyError:
            pass

        try:
            ct = self.get(service=query_service, app_label=opts.app_label, model=opts.model_name)
        except self.model.DoesNotExist:
            raise RuntimeError(
                f'Could not find content type for {(query_service, opts.app_label, opts.model_name)}, '
                'and creating new objects via get_for_model is not allowed for DAB RBAC'
            )
        self._add_to_cache(self.db, ct)
        return ct

    def get_for_models(
        self,
        *model_list: Union[Type[django_models.Model], django_models.Model],
        for_concrete_models: bool = True,
    ) -> Dict[Type[django_models.Model], django_models.Model]:
        """Return ``DABContentType`` objects for each model in ``model_list``.

        This gets deep into the customization of unique rules for DAB RBAC.
        We require that model_name must be unique for a given service,
        and this will rely on that assumption, which compares to app_label
        in the original ContentType model.
        """
        results: Dict[Type[django_models.Model], django_models.Model] = {}
        # A keyed by (service, app_name) unlike Django where it was just app_name
        needed_models: Dict[Tuple[str, str], set[str]] = defaultdict(set)
        # A dict of (service, app_name, model_name), differs from Django ContentType
        # in Django content type it was (app_name, model_name)
        needed_opts: Dict[Tuple[str, str, str], list[Type[django_models.Model]]] = defaultdict(list)
        for model in model_list:
            opts = self._get_opts(model, for_concrete_models)
            # For local models, this will give the local service name of "shared" for shared models
            model_service = get_resource_prefix(model)
            try:
                ct = self._get_from_cache(opts, model_service)
            except KeyError:
                needed_models[(model_service, opts.app_label)].add(opts.model_name)
                needed_opts[(model_service, opts.app_label, opts.model_name)].append(model)  # type: ignore[index]
            else:
                results[model] = ct  # type: ignore[index]

        if needed_opts:
            condition = django_models.Q(
                *(
                    django_models.Q(
                        ("service", service_search),  # To not shadow var from prior loop
                        ("app_label", app_label),
                        ("model__in", models),
                    )
                    for (service_search, app_label), models in needed_models.items()
                ),
                _connector=django_models.Q.OR,
            )
            cts = self.filter(condition)
            for ct in cts:
                opts_models = needed_opts.pop((ct.service, ct.app_label, ct.model), [])
                for model in opts_models:
                    results[model] = ct
                self._add_to_cache(self.db, ct)
            if needed_opts:
                raise RuntimeError(
                    f'Could not find content type for any of {needed_opts.keys()}, '
                    f'and creating new objects via get_for_models is not enabled for DAB RBAC, looked in:\n{needed_models.keys()}'
                )
        return results

    def get_by_natural_key(self, *args: str) -> django_models.Model:
        """Return the content type identified by its natural key.

        Note that we can not type hint the return value fully because it is used in migrations.
        Migrations will return a prior model state.
        """
        if len(args) == 2:
            service = get_local_resource_prefix()
            app_label, model = args
            kwargs = {'service__in': [get_local_resource_prefix(), 'shared'], 'app_label': app_label, 'model': model}
            # This ask here is actually ambiguous, so we try this extra lookup
            shared_key = ('shared', app_label, model)
            if shared_key in self._cache.get(self.db, ()):
                return self._cache[self.db][shared_key]
        else:
            service, app_label, model = args
            kwargs = {'service': service, 'app_label': app_label, 'model': model}
        key = (service, app_label, model)
        try:
            return self._cache[self.db][key]
        except KeyError:
            # Here we are adding additional error details for migration problems
            ct = self.filter(**kwargs).first()
            if ct is None:
                raise self.model.DoesNotExist(f'Could not get ContentType {args}, existing: {list(self.values_list("model", flat=True))}')
            self._add_to_cache(self.db, ct)
            return ct

    def get_for_id(self, id: int) -> django_models.Model:
        """Return the content type with primary key ``id`` from the cache."""
        try:
            return self._cache[self.db][id]
        except KeyError:
            ct = self.get(pk=id)
            self._add_to_cache(self.db, ct)
            return ct

    def load_remote_objects(self, remote_data: list[dict]):
        parent_mapping: dict[django_models.Model, str] = {}
        # For test reasons, it can be very hard to assure the post_migrate logic runs in all cases
        # so we just put in the id field manually which avoids any conflict with existing records
        max_id = self.aggregate(Max('id'))['id__max'] or 0
        for remote_type_raw in remote_data:
            defaults = remote_type_raw.copy()
            service = defaults.pop('service')
            model = defaults.pop('model')
            pct_slug = defaults.pop('parent_content_type')
            max_id += 1
            defaults['id'] = max_id
            ct, _ = self.get_or_create(service=service, model=model, defaults=defaults)
            parent_mapping[ct] = pct_slug

        # The parent type link needs to be filled in via a second pass
        for ct, pct_slug in parent_mapping.items():
            if pct_slug and (ct.parent_content_type_id is None or ct.parent_content_type.api_slug != pct_slug):
                ct.parent_content_type = DABContentType.objects.get(api_slug=pct_slug)
                ct.save()

    def warm_cache(self, queryset=None):
        "Put objects from the given queryset into the cache, or all objects"
        if queryset is None:
            queryset = self.all()

        for ct in queryset:
            self._add_to_cache(self.db, ct)


class DABContentType(django_models.Model):
    """Like Django ContentType model but scoped by service."""

    service = django_models.CharField(
        max_length=100,
        default=get_local_resource_prefix,
        help_text=_("service namespace to track what service this type is for. Can have a value of shared, which indicates it is synchronized."),
    )
    app_label = django_models.CharField(
        max_length=100,
        help_text=_("Django app that the model is in. This is an internal technical detail that does not affect API use."),
    )
    model = django_models.CharField(
        max_length=100,
        help_text=_("Name of the type according to the Django ORM Meta model_name convention. Comes from the python class, but lowercase with no spaces."),
    )
    parent_content_type = django_models.ForeignKey(
        "self",
        null=True,
        help_text=_("Parent model within the RBAC system. Being assigned to a role in objects of the parent model can confer permissions to child objects."),
        on_delete=django_models.SET_NULL,
        related_name='child_content_types',
    )
    api_slug = django_models.CharField(
        max_length=201,  # combines service and model fields with a period in-between
        default='',  # will be set by the saving or creation logic
        help_text=_("String to use for references to this type from other models in the API."),
    )
    pk_field_type = django_models.CharField(
        max_length=100,
        default='integer',
        help_text=_("Database field type of the primary key field of the model, relevant for interal logic tracking permissions."),
    )

    objects = DABContentTypeManager()

    class Meta:
        unique_together = [
            # Explanation: normally these are unique on (app_label, model_name)
            # DAB RABC imposes, as an additional constraint,
            # that a single service can only continute a single model to the collective
            ("service", "model"),
        ]
        ordering = ['id']

    def __str__(self) -> str:
        return self.app_labeled_name

    @property
    def name(self) -> str:
        model = self.model_class()
        if not model:
            return self.model
        return str(model._meta.verbose_name)

    @property
    def app_labeled_name(self) -> str:
        model = self.model_class()
        if not model:
            return self.model
        if issubclass(model, RemoteObject):
            return f'RemoteObject | {self.model}'
        return f"{model._meta.app_config.verbose_name} | {model._meta.verbose_name}"

    def save(self, *args, **kwargs):
        # Set the api_slug field if it is not synchronized to other fields
        api_slug = f'{self.service}.{self.model}'
        if api_slug != self.api_slug:
            self.api_slug = api_slug
            if update_fields := kwargs.get('update_fields', []):
                update_fields.append('api_slug')
        return super().save(*args, **kwargs)

    def model_class(self) -> Union[Type[django_models.Model], Type[RemoteObject]]:
        """Return the model class or a stand-in.

        So it could return a Django model class or a python class.
        """
        if self.service not in ("shared", get_local_resource_prefix()):
            from ..remote import get_remote_standin_class

            return get_remote_standin_class(self)

        try:
            return apps.get_model(self.app_label, self.model)
        except LookupError as exc:
            raise LookupError(
                f'Could not find ({self.app_label}, {self.model}), expected in local service={get_local_resource_prefix()} object service={self.service}'
            ) from exc

    def get_object_for_this_type(self, **kwargs: Any) -> Union[django_models.Model, RemoteObject]:
        """Return the object referenced by this content type."""
        model = self.model_class()

        from ..remote import get_remote_base_class

        remote_base = get_remote_base_class()

        if issubclass(model, remote_base):
            object_id = kwargs.get("pk") or kwargs.get("id") or kwargs.get("pk__exact") or kwargs.get("id__exact")
            if object_id is None:
                raise LookupError("Model id was not provided")
            return model(self, object_id)

        return model._base_manager.get(**kwargs)

    def get_all_objects_for_this_type(self, **kwargs: Any) -> Union[django_models.QuerySet, Sequence[Union[django_models.Model, RemoteObject]]]:
        """Return all objects referenced by this content type."""
        model = self.model_class()

        from ..remote import get_remote_base_class

        remote_base = get_remote_base_class()
        if issubclass(model, remote_base):
            ids = kwargs.get("pk__in") or kwargs.get("id__in") or (kwargs.get("pk") and [kwargs["pk"]]) or (kwargs.get("id") and [kwargs["id"]])
            if not ids:
                return []
            return [model(self, obj_id) for obj_id in ids]

        return list(model._base_manager.filter(**kwargs))

    def natural_key(self) -> Tuple[str, str, str]:
        return (self.service, self.app_label, self.model)

    @property
    def is_remote(self):
        return self.service not in ('shared', get_local_resource_prefix())
