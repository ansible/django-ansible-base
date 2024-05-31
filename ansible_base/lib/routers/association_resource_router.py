import copy
import logging
from itertools import chain
from typing import Type

from django.conf import settings
from django.db.models import Model
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


# Registry contains subclasses of AssociationSerializerBase indexed by name
# this prevents duplicate names which would cause schema to not render correctly
serializer_registry = {}


class AssociationSerializerBase(serializers.Serializer):
    """It is expected that final subclasses will set the instances field"""

    instances = None

    def get_queryset_on_init(self, original_qs: QuerySet) -> QuerySet:
        raise NotImplementedError

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        new_qs = self.get_queryset_on_init(self.fields['instances'].child_relation.queryset)
        self.fields['instances'].child_relation.queryset = new_qs


class DisassociationSerializerBase(AssociationSerializerBase):
    """Serializer used for removing objects that are currently associated via a many-to-many relationship"""

    def get_queryset_on_init(self, original_qs: QuerySet) -> QuerySet:
        if 'view' in self.context:
            view = self.context['view']
            if 'pk' in view.kwargs:
                return view.get_queryset()
        return original_qs

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['instances'].child_relation.error_messages = self.fields['instances'].child_relation.error_messages.copy()
        self.fields['instances'].child_relation.error_messages['does_not_exist'] = _(
            'Invalid pk "{pk_value}" - object does not exist or is not associated with parent object.'
        )


class FilteredAssociationSerializer(AssociationSerializerBase):
    """Serializer used for adding objects to a many-to-many relationship"""

    def get_queryset_on_init(self, original_qs: QuerySet) -> QuerySet:
        if 'view' in self.context:
            # If the view exists we require it to be an instance of AssociationViewSetMethodsMixin
            view = self.context['view']
            return view.filter_associate_queryset(original_qs)
        return original_qs


class AssociationViewSetMethodsMixin:
    """Contains methods called by viewset methods for list, associate, disassociate actions

    Importantly, this is placed high up in the inheritance chain.
    This means that the viewset passed in for the related views can override these methods.
    General principal is that these should not overlap with DRF methods, because those
    are likely already defined by the passed-in viewset and will not take effect.
    """

    def filter_associate_queryset(self, qs: QuerySet) -> QuerySet:
        """Limits queryset to objects allowed to be associated

        This is allowed to be different from the filter for the list view,
        which affects what is visible to the user.
        Compare to this, which defines what objects can be _associated_
        probably due to permission restrictions... normally based on visibility.
        """
        return self.filter_queryset(qs)

    def get_sublist_queryset(self, parent_instance: Model) -> QuerySet:
        """Queryset to show, given a parent object

        Example would be /organizations/N/teams/
        This method returns the team queryset, given organization object pk=N
        """
        return getattr(parent_instance, self.association_fk).all()

    def perform_associate(self, parent_instance: Model, related_instances: list[Model]) -> None:
        """Attach related_instances to instance via the relationship this viewset manages"""
        manager = getattr(parent_instance, self.association_fk)
        manager.add(*related_instances)

    def perform_disassociate(self, parent_instance: Model, related_instances: list[Model]) -> None:
        """Remove related_instances from the managed relationship of instance"""
        manager = getattr(parent_instance, self.association_fk)
        manager.remove(*related_instances)


class RelatedListMixin:
    """Mixin used for related viewsets which contain a sub-list, like /organizations/N/teams/"""

    def check_parent_object_permissions(self, request, parent_obj: Model) -> None:
        """Check that request user has permission to parent_obj

        Associate and disassociate is a POST request, list is GET
        the normal process of get_object --> check_object_permissions
        will not check "change" permissions to the parent object on POST
        this method checks parent change permission, view permission should be handled by filter_queryset
        """
        if (request.method not in SAFE_METHODS) and 'ansible_base.rbac' in settings.INSTALLED_APPS and permission_registry.is_registered(parent_obj):
            from ansible_base.rbac.policies import check_content_obj_permission

            check_content_obj_permission(request.user, parent_obj)

    def get_parent_object(self) -> Model:
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

    def get_queryset(self) -> QuerySet:
        parent_instance = self.get_parent_object()
        return self.get_sublist_queryset(parent_instance)


class AssociateMixin(RelatedListMixin):
    """Mixin used for writable related viewsets, where objects can be associated or disassociated from the relationship"""

    instances_help_text = {
        'associate': _('List of {model_name} to add to this relationship'),
        'disassociate': _('List of {model_name} to remove from this relationship'),
    }
    parent_serializer_cls = {'associate': FilteredAssociationSerializer, 'disassociate': DisassociationSerializerBase}

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

        self.perform_associate(instance, related_instances)

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

        self.perform_disassociate(instance, related_instances)

        return Response(status=status.HTTP_204_NO_CONTENT)

    def get_viewset_model(self) -> Type[Model]:
        """Return model for this viewset"""
        if self.queryset:
            return self.queryset.model
        return self.serializer_class.Meta.model

    def get_serializer_class(self) -> Type[serializers.BaseSerializer]:
        if self.action in ('disassociate', 'associate'):
            cls = self.get_viewset_model()
            pretty_model_name = cls._meta.verbose_name.title().replace(' ', '')
            cls_name = f'{pretty_model_name}{self.action.title()}Serializer'

            default_instances_field = serializers.PrimaryKeyRelatedField(
                queryset=cls.objects.all(), many=True, help_text=self.instances_help_text[self.action].format(model_name=cls._meta.verbose_name_plural)
            )

            if cls_name not in serializer_registry:
                serializer_registry[cls_name] = type(cls_name, (self.parent_serializer_cls[self.action],), {'instances': default_instances_field})
            return serializer_registry[cls_name]

        return super().get_serializer_class()


@property
def attribute_raiser(cls):
    """This method is used to exclude methods in subclass of provided viewset

    How it works:
    SimpleRouter.get_method_map determines what actions are in a viewset with hasattr.
    raising AttributeError makes that return False, so methods like retrieve
    will not be included in the returned method map, so it will not build a URL
    for those, because we do not want them in the association URL set.
    """
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

        custom_methods = chain.from_iterable(action.mapping.values() for action in viewset.get_extra_actions())

        exclude_list = ('retrieve', 'update', 'partial_update', 'destroy') + tuple(custom_methods)

        class AssociatedViewSetType(type(viewset)):
            """Metaclass that turns off viewset methods other than list"""

            method_excludes = exclude_list

            def __dir__(self):
                ret = list(super().__dir__())
                for method in self.method_excludes:
                    if method in ret:
                        ret.remove(method)
                return ret

        for method in exclude_list:
            setattr(AssociatedViewSetType, method, attribute_raiser)

        class AssociatedViewSet(viewset, AssociationViewSetMethodsMixin, metaclass=AssociatedViewSetType):
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
