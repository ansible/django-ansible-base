import logging

from django.conf import settings
from django.db.models.fields import IntegerField
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from rest_framework import routers, serializers, status
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response

from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.rbac.policies import check_content_obj_permission

logger = logging.getLogger('ansible_base.lib.routers.association_resource_router')


class QuerySetMixinBase:
    def get_queryset(self):
        parent_pk = self.kwargs['pk']
        parent_model = self.parent_viewset.serializer_class.Meta.model

        try:
            parent_instance = parent_model.objects.get(pk=parent_pk)
        except parent_model.DoesNotExist:
            return parent_model.objects.none()

        child_queryset = getattr(parent_instance, self.association_fk).all()
        return child_queryset


class AssociateMixin(QuerySetMixinBase):
    def check_parent_object_permissions(self, request, parent_obj):
        # Because this is a POST request, the normal process in parent_view of
        # get_object --> check_object_permissions
        # will not check "change" permissions to the parent object
        # this method is a replacement for that flow for both attaching and detatching
        if (request.method not in SAFE_METHODS) and 'ansible_base.rbac' in settings.INSTALLED_APPS and permission_registry.is_registered(parent_obj):
            return check_content_obj_permission(request.user, parent_obj)
        return True

    def get_parent_object(self):
        """Modeled mostly after DRF get_object

        This is kept separate to be more manual and explicit
        """
        parent_view = self.parent_viewset()
        parent_view.request = self.request
        queryset = parent_view.filter_queryset(parent_view.get_queryset())
        filter_kwargs = {'pk': self.kwargs['pk']}

        parent_obj = get_object_or_404(queryset, **filter_kwargs)

        # May raise a permission denied
        self.check_parent_object_permissions(self.request, parent_obj)

        return parent_obj

    def list(self, *args, **kwargs):
        "Override list strictly for purpose of checking parent object permission"
        self.get_parent_object()
        return super().list(*args, **kwargs)

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

    def get_serializer_class(self):
        association_class = getattr(self, 'association_serializer', None)
        if self.action in ('associate', 'disassociate'):
            if association_class is None:
                raise RuntimeError('You must set association_serializer on the viewset')
            return association_class
        return super().get_serializer_class()


class ReverseViewMixin(QuerySetMixinBase):
    pass


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

    def association_serializer_factory(self, related_view):
        qs = related_view.queryset
        if qs is None:
            qs = related_view.serializer_class.Meta.model.objects.all()

        class AssociationSerializer(serializers.Serializer):
            instances = serializers.PrimaryKeyRelatedField(
                queryset=qs,
                many=True,
            )

        return AssociationSerializer

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
                mixin_class = ReverseViewMixin

            # Generate the related viewset
            modified_related_viewset = type(
                f'Related{related_view.__name__}',
                (mixin_class, related_view),
                {
                    'association_fk': fk,
                    'parent_viewset': viewset,
                    'association_serializer': self.association_serializer_factory(related_view),
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
