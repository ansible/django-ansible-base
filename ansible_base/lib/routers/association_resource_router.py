import logging

from django.db.models.fields import IntegerField
from django.utils.translation import gettext as _
from rest_framework import routers, serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response

logger = logging.getLogger('ansible_base.lib.routers.association_resource_router')


class QuerySetMixinBase:
    def get_queryset(self):
        parent_pk = self.kwargs['pk']
        parent_model = self.parent_view_model

        try:
            parent_instance = parent_model.objects.get(pk=parent_pk)
        except parent_model.DoesNotExist:
            return parent_model.objects.none()

        child_queryset = getattr(parent_instance, self.association_fk).all()
        return child_queryset


class AssociateMixin(QuerySetMixinBase):
    @action(detail=False, methods=['post'])
    def associate(self, request, **kwargs):
        """
        Associate a related object with this object.

        This will be served at /{basename}/{pk}/{related_name}/associate/
        We will be given a list of primary keys in the request body.
        """
        instance = self.parent_view_model.objects.get(pk=kwargs['pk'])
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
        instance = self.parent_view_model.objects.get(pk=kwargs['pk'])
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
                    'parent_view_model': parent_model,
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
