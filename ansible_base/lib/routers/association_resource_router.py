from django.utils.translation import gettext as _
from rest_framework import routers, serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response


class AssociateMixin:
    @action(detail=False, methods=['post'])
    def associate(self, request, **kwargs):
        """
        Associate a related object with this object.

        This will be served at /{basename}/{pk}/{related_name}/associate/
        We will be given a list of primary keys in the request body.
        """
        instance = self.backward_related_qs.get(pk=kwargs['pk'])
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
        instance = self.backward_related_qs.get(pk=kwargs['pk'])
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

        try:
            manager.remove(*related_instances)
        except AttributeError:
            # If the field is FK and non-nullable, .remove() won't exist.
            # https://docs.djangoproject.com/en/dev/ref/models/relations/#django.db.models.fields.related.RelatedManager.remove
            # "For ForeignKey objects, this method only exists if null=True."
            # Return something stating that the operation is not supported.
            raise serializers.ValidationError(
                {
                    'instances': _('Cannot disassociate these objects because there must be a related object'),
                }
            )

        return Response(status=status.HTTP_204_NO_CONTENT)

    def get_serializer_class(self):
        association_class = getattr(self, 'association_serializer', None)
        if self.action in ('associate', 'disassociate'):
            if association_class is None:
                raise RuntimeError('You must set association_serializer on the viewset')
            return association_class
        return super().get_serializer_class()

    def get_queryset(self):
        parent_pk = self.kwargs['pk']
        parent_model = self.backward_related_qs.model

        try:
            parent_instance = parent_model.objects.get(pk=parent_pk)
        except parent_model.DoesNotExist:
            return parent_model.objects.none()

        child_queryset = getattr(parent_instance, self.association_fk).all()
        return child_queryset


class ReverseViewMixin:
    def get_serializer_class(self):
        related_class = getattr(self, 'related_serializer', None)
        if self.action in ('associate', 'disassociate'):
            if related_class is None:
                raise RuntimeError('You must set related_serializer on the viewset')
            return related_class
        return super().get_serializer_class()

    def get_queryset(self):
        parent_pk = self.kwargs['pk']
        parent_model = self.backward_related_qs.model

        try:
            parent_instance = parent_model.objects.get(pk=parent_pk)
        except parent_model.DoesNotExist:
            return parent_model.objects.none()

        child_queryset = getattr(parent_instance, self.related_fk).all()
        return child_queryset


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

    def register(self, prefix, viewset, basename=None, related_views={}, reverse_views={}):
        if basename is None:
            basename = self.get_default_basename(viewset)

        for reverse_name, (reverse_view, fk) in reverse_views.items():

            def related_serializer_factory(reverse_view=reverse_view):
                class RelatedSerializer(serializers.Serializer):
                    instances = serializers.PrimaryKeyRelatedField(
                        queryset=reverse_view.queryset,
                        many=True,
                    )

                return RelatedSerializer

            modified_reverse_viewset = type(
                f'Reverse{reverse_view.__name__}',
                (ReverseViewMixin, reverse_view),
                {
                    'related_fk': fk,
                    'backward_related_qs': viewset.queryset,
                    'related_serializer': related_serializer_factory(),
                    'lookup_field': fk,
                },
            )
            # Force the view to be read only
            modified_reverse_viewset.http_method_names = ['get', 'head', 'options']

            self.registry.append((f"{prefix}/(?P<pk>[^/.]+)/{reverse_name}", modified_reverse_viewset, f'{basename}-{fk}'))

        for related_name, (related_view, fk) in related_views.items():

            def association_serializer_factory(related_view=related_view):
                class AssociationSerializer(serializers.Serializer):
                    instances = serializers.PrimaryKeyRelatedField(
                        queryset=related_view.queryset,
                        many=True,
                    )

                return AssociationSerializer

            modified_related_viewset = type(
                f'Related{related_view.__name__}',
                (AssociateMixin, related_view),
                {
                    'association_fk': fk,
                    'backward_related_qs': viewset.queryset,
                    'association_serializer': association_serializer_factory(),
                    'lookup_field': fk,
                },
            )

            self.registry.append((f"{prefix}/(?P<pk>[^/.]+)/{related_name}", modified_related_viewset, f'{basename}-{fk}'))

        super().register(prefix, viewset, basename)
