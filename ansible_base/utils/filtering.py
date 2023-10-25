from django.db import models
from django_filters import FilterSet, OrderingFilter
from django_filters import rest_framework as filters
from django_filters.filterset import FILTER_FOR_DBFIELD_DEFAULTS
from django_filters.utils import try_dbfield

SUPPORTED_LOOKUPS = {
    'exact',
    'iexact',
    'contains',
    'icontains',
    'startswith',
    'istartswith',
    'endswith',
    'iendswith',
    'regex',
    'iregex',
    'gt',
    'gte',
    'lt',
    'lte',
    'in',
    'isnull',
    'search',
}

IGNORED_FIELDS = "password"


def get_fields(model, prefix=""):
    fields = {}

    for field in model._meta.get_fields():
        # add filters for foreign keys up to one level in depth
        if type(field) is models.ForeignKey and prefix == "":
            fields.update(get_fields(field.remote_field.model, prefix=field.name + "__"))

        if try_dbfield(FILTER_FOR_DBFIELD_DEFAULTS.get, field.__class__) and field.name not in IGNORED_FIELDS:
            if not prefix:
                lookups = set(field.get_lookups().keys())
            else:
                lookups = {
                    'exact',
                }

            # many to many and one to many cause "in" to break
            # see https://github.com/carltongibson/django-filter/issues/1103
            if field.many_to_many or field.one_to_many:
                if "in" in lookups:
                    lookups.remove("in")

            fields[prefix + field.name] = list(lookups.intersection(SUPPORTED_LOOKUPS))

    return fields


class AutomaticDjangoFilterBackend(filters.DjangoFilterBackend):
    generated_classes = {}

    def get_filterset_class(self, view, queryset=None):
        """
        Generates a filterset class for viewset's model which does the following:
            - Creates a filter for each field on the model
            - Add a lookup expression (icontains, exact, lte, etc.) for each expression that
              the field type supports, that's also in SUPPORTED_LOOKUPS
            - Fields defined in IGNORED_FIELDS are not included in the filterset
            - Repeat for any foreign key fields, up to a depth of 1. (ie foo__bar__exact is supported
              but foo__bar__foobar__exact is not)
            - Each field that supports a filter is added to order_by

        Usage:
            Set filter_backends = (CustomFilterBackend,) on your viewset.

            TODO: allow viewsets or models to declare fields that can't be filtered.
        """
        model = queryset.model
        name = str("%sFilterSet" % model._meta.object_name)
        if cached := self.generated_classes.get(name):
            return cached

        fields = get_fields(model)

        # ignore foreign key lookups for filtering
        order_fields = [(f, f) for f in fields if "__" not in f]

        meta = type(str("Meta"), (object,), {"model": model, "fields": fields})

        filterset = type(
            name,
            (FilterSet,),
            {
                "Meta": meta,
                "order_by": OrderingFilter(fields=order_fields),
            },
        )
        self.generated_classes[name] = filterset
        return filterset
