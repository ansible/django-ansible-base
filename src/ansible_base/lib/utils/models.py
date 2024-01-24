from itertools import chain

from inflection import underscore


def get_all_field_names(model):
    # Implements compatibility with _meta.get_all_field_names
    # See: https://docs.djangoproject.com/en/1.11/ref/models/meta/#migrating-from-the-old-api
    return list(
        set(
            chain.from_iterable(
                (field.name, field.attname) if hasattr(field, 'attname') else (field.name,)
                for field in model._meta.get_fields()
                # For complete backwards compatibility, you may want to exclude
                # GenericForeignKey from the results.
                if not (field.many_to_one and field.related_model is None)
            )
        )
    )


def get_type_for_model(model):
    """
    Return type name for a given model class.
    """
    opts = model._meta.concrete_model._meta
    return underscore(opts.object_name)


def prevent_search(relation):
    """
    Used to mark a model field or relation as "restricted from filtering"
    e.g.,

    class AuthToken(BaseModel):
        user = prevent_search(models.ForeignKey(...))
        sensitive_data = prevent_search(models.CharField(...))

    The flag set by this function is used by
    `ansible_base.rest_filters.rest_framework.field_lookup_backend.FieldLookupBackend` to block fields and relations that
    should not be searchable/filterable via search query params
    """
    setattr(relation, '__prevent_search__', True)
    return relation
