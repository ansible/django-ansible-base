import copy
import logging
from itertools import chain
from typing import Type

from django.conf import settings
from django.db.models.fields import IntegerField
from django.db.models.query import QuerySet
from django.http import QueryDict
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from rest_framework import routers, serializers, status
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS
from rest_framework.request import clone_request
from rest_framework.response import Response
from rest_framework.viewsets import ViewSetMixin

from ansible_base.rbac.permission_registry import permission_registry

logger = logging.getLogger('ansible_base.lib.routers.association_resource_router')


class RelatedListMixin:
    def check_parent_object_permissions(self, request, parent_obj):
        # Associate and disassociate is a POST request, list is GET
        # the normal process of get_object --> check_object_permissions
        # will not check "change" permissions to the parent object on POST
        # this method checks parent change permission, view permission should be handled by filter_queryset
        if (request.method not in SAFE_METHODS) and 'ansible_base.rbac' in settings.INSTALLED_APPS and permission_registry.is_registered(parent_obj):
            from ansible_base.rbac.policies import check_content_obj_permission

            return check_content_obj_permission(request.user, parent_obj)
        return True

    def get_parent_object(self):
        """Modeled mostly after DRF get_object, but for the parent model

        Like for /api/v2/organizations/<pk>/cows/, this returns the organization
        with the specified pk.
        """
        parent_view = self.parent_viewset()
        parent_view.request = clone_request(self.request, 'GET')
        parent_view.request._request = copy.copy(self.request._request)
        parent_view.request._request.GET = QueryDict()
        queryset = parent_view.filter_queryset(parent_view.get_queryset())
        filter_kwargs = {'pk': self.kwargs['pk']}
        parent_obj = get_object_or_404(queryset, **filter_kwargs)

        # May raise a permission denied
        self.check_parent_object_permissions(self.request, parent_obj)

        return parent_obj

    def get_queryset(self):
        parent_instance = self.get_parent_object()
        return getattr(parent_instance, self.association_fk).all()


class AssociationSerializerBase(serializers.Serializer):
    """Serializer used for associating related objects, where all those related objects are allowed

    It is expected that subclasses will set target_queryset which gives the queryset
    for the model that will be associated"""

    target_queryset = None

    def get_queryset_on_init(self, request) -> QuerySet:
        return self.target_queryset

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context['request']
        self.fields['instances'] = serializers.PrimaryKeyRelatedField(queryset=self.get_queryset_on_init(request), many=True)


# Registry contains subclasses of AssociationSerializerBase indexed by name
# this prevents duplicate names which would cause schema to not render correctly
serializer_registry = {}


class AssociateMixin(RelatedListMixin):
    @action(detail=False, methods=['post'])
    def associate(self, request, **kwargs):
        """
        Associate a related object with this object.

        This will be served at /{basename}/{pk}/{related_name}/associate/
        We will be given a list of primary keys in the request body.
        """
        instance = self.get_parent_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        related_instances = serializer.validated_data['instances']
        if not related_instances:
            raise serializers.ValidationError({'instances': _('Please pass in one or more instances to associate')})
        manager = getattr(instance, self.association_fk)
        manager.add(*related_instances)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['post'])
    def disassociate(self, request, **kwargs):
        """
        Disassociate a related object from this object.

        This will be served at /{basename}/{pk}/{related_name}/disassociate/
        We will be given a list of primary keys in the request body.
        """
        instance = self.get_parent_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        related_instances = serializer.validated_data['instances']
        if not related_instances:
            raise serializers.ValidationError({'instances': _('Please pass in one or more instances to disassociate')})
        manager = getattr(instance, self.association_fk)

        # Ensure each of the given related_instances is actually related to the instance.
        # If any isn't, then bomb out and tell the user which ones aren't related.
        given_related_instance_set = set(related_instances)
        related_instance_set = set(manager.all())
        non_related_instances = given_related_instance_set - related_instance_set
        if non_related_instances:
            raise serializers.ValidationError(
                {
                    'instances': _('Cannot disassociate these objects because they are not all related to this object: %(non_related_instances)s')
                    % {'non_related_instances': ', '.join(str(i.pk) for i in non_related_instances)},
                }
            )

        manager.remove(*related_instances)

        return Response(status=status.HTTP_204_NO_CONTENT)

    def get_association_queryset(self) -> QuerySet:
        if self.queryset:
            qs = self.queryset
            cls = self.queryset.model
        else:
            cls = self.serializer_class.Meta.model
            qs = cls.objects.all()

        if self.action == 'associate':
            if hasattr(self, 'filter_associate_queryset'):
                return self.filter_associate_queryset(qs)
            else:
                return self.filter_queryset(qs)
        return qs

    def get_serializer_class(self):
        if self.action in ('disassociate', 'associate'):
            qs = self.get_association_queryset()

            rel_name = self.association_fk.replace('_', ' ').title().replace(' ', '')
            cls_name = f'{self.parent_viewset.__name__}{rel_name}AssociationSerializer'

            if cls_name not in serializer_registry:
                serializer_registry[cls_name] = type(cls_name, (AssociationSerializerBase,), {'target_queryset': qs})
            return serializer_registry[cls_name]

        return super().get_serializer_class()


@property
def attribute_raiser(cls):
    raise AttributeError


class AssociationResourceRouter(routers.SimpleRouter):
    def get_method_map(self, viewset, method_map):
        is_associate_viewset = issubclass(viewset, AssociateMixin)
        associate_actions = ['associate', 'disassociate', 'list']
        bound_methods = {}
        for method, action_str in method_map.items():
            if hasattr(viewset, action_str):
                if is_associate_viewset and action_str not in associate_actions:
                    continue
                bound_methods[method] = action_str
        return bound_methods

    def associated_viewset_cls_factory(self, viewset: Type[ViewSetMixin]) -> Type[ViewSetMixin]:
        """Given viewset (as a class) return a subclass containing all its actions except for list"""

        class AssociatedViewSetType(type(viewset)):
            """Metaclass that turns off viewset methods other than list"""

            pass

        custom_methods = chain.from_iterable(action.mapping.values() for action in viewset.get_extra_actions())

        for method in ('retrieve', 'update', 'partial_update', 'destroy') + tuple(custom_methods):
            setattr(AssociatedViewSetType, method, attribute_raiser)

        class AssociatedViewSet(viewset, metaclass=AssociatedViewSetType):
            """Adjusted version of given viewset for related endpoint with only list views"""

            pass

        return AssociatedViewSet

    def register(self, prefix, viewset, related_views={}, basename=None):
        if basename is None:
            basename = self.get_default_basename(viewset)

        for related_name, (related_view, fk) in related_views.items():
            parent_model = viewset.serializer_class.Meta.model
            child_model = related_view.serializer_class.Meta.model

            # Determine if this is a related view or a reverse view
            is_reverse_view = False
            mixin_class = AssociateMixin
            if any(x.related_model == child_model for x in parent_model._meta.related_objects):
                is_reverse_view = True
                mixin_class = RelatedListMixin

            # Start with a viewset that only has list action enabled
            associated_viewset = self.associated_viewset_cls_factory(related_view)

            # Generate the related viewset
            # Name includes and parent and child viewset, because this defines global uniqueness
            modified_related_viewset = type(
                f'Related{viewset.__name__}{related_view.__name__}',
                (mixin_class, associated_viewset),
                {
                    'association_fk': fk,
                    'parent_viewset': viewset,
                    'lookup_field': fk,
                },
            )

            # Force a reverse view to be read only
            if is_reverse_view:
                modified_related_viewset.http_method_names = ['get', 'head', 'options']

            if isinstance(child_model._meta.pk, IntegerField):
                url_path = f"{prefix}/(?P<pk>[0-9]+)/{related_name}"
            else:
                url_path = f"{prefix}/(?P<pk>[^/.]+)/{related_name}"

            # Register the viewset
            self.registry.append((url_path, modified_related_viewset, f'{basename}-{fk}'))

        super().register(prefix, viewset, basename)
