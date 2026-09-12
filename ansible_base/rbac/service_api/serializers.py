import logging

from crum import impersonate
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from ..api.fields import ActorAnsibleIdField
from ..models import DABContentType, DABPermission, RoleDefinition, RoleTeamAssignment, RoleUserAssignment
from ..policies import check_content_obj_permission
from ..remote import RemoteObject

logger = logging.getLogger('ansible_base.rbac.service_api.serializers')


class DABContentTypeSerializer(serializers.ModelSerializer):
    parent_content_type = serializers.SlugRelatedField(read_only=True, slug_field='api_slug')

    class Meta:
        model = DABContentType
        fields = ['api_slug', 'service', 'app_label', 'model', 'parent_content_type', 'pk_field_type']


class DABPermissionSerializer(serializers.ModelSerializer):
    content_type = serializers.SlugRelatedField(read_only=True, slug_field='api_slug')

    class Meta:
        model = DABPermission
        fields = ['api_slug', 'codename', 'content_type', 'name']


# 'id' is included so consumers can implement cursor-based pagination
# (e.g. id__gt=<last_pk>&order_by=id) for efficient resume after
# crashes and skip-on-reinstall in migrate_service_data.
assignment_common_fields = ('id', 'created', 'created_by_ansible_id', 'object_id', 'object_ansible_id', 'content_type', 'role_definition')


class BaseAssignmentSerializer(serializers.ModelSerializer):
    content_type = serializers.SlugRelatedField(read_only=True, slug_field='api_slug')
    role_definition = serializers.SlugRelatedField(slug_field='name', queryset=RoleDefinition.objects.all())
    created_by_ansible_id = ActorAnsibleIdField(source='created_by', required=False, allow_null=True)
    object_ansible_id = serializers.UUIDField(required=False, allow_null=True)
    object_id = serializers.CharField(allow_blank=True, required=False, allow_null=True)
    from_service = serializers.CharField(write_only=True)

    def validate(self, attrs):
        """The object_id vs ansible_id is the only dual-write case, where we have to accept either

        So this does the mutual validation to assure we have sufficient data.
        """
        rd = attrs['role_definition']
        has_object_id = 'object_id' in attrs and attrs['object_id']
        has_object_ansible_id = 'object_ansible_id' in attrs and attrs['object_ansible_id']

        if rd.content_type_id:
            if not self.partial and not has_object_id and not has_object_ansible_id:
                raise serializers.ValidationError("You must provide either 'object_id' or 'object_ansible_id'.")
            if has_object_ansible_id:
                from ansible_base.resource_registry.models import Resource

                try:
                    resource = Resource.objects.get(ansible_id=attrs['object_ansible_id'])
                except Resource.DoesNotExist:
                    raise serializers.ValidationError({'object_ansible_id': "Resource with this ansible_id does not exist."})
                attrs['object_id'] = resource.object_id
        else:
            if has_object_id or has_object_ansible_id:
                raise serializers.ValidationError("Can not provide either 'object_id' or 'object_ansible_id' for system role")

        return super().validate(attrs)

    def find_existing_assignment(self, queryset):
        actor = self.validated_data[self.actor_field]
        role_definition = self.validated_data['role_definition']
        filter_kwargs = {self.actor_field: actor, 'role_definition': role_definition}
        if role_definition.content_type_id:
            filter_kwargs['object_id'] = self.validated_data['object_id']
        else:
            filter_kwargs['object_id'] = None
        return queryset.filter(**filter_kwargs).first()

    def create(self, validated_data):
        rd = validated_data['role_definition']
        actor = validated_data[self.actor_field]
        requesting_user = self.context['view'].request.user

        as_user = None
        if 'created_by' in validated_data:
            as_user = validated_data['created_by']

        # Unlike the public view, the action is attributed to the specified user in data
        with impersonate(as_user):

            object_id = validated_data.get('object_id')
            obj = None
            if object_id:
                model = rd.content_type.model_class()

                if issubclass(model, RemoteObject):
                    obj = model(content_type=rd.content_type, object_id=object_id)
                else:
                    try:
                        obj = model.objects.get(pk=object_id)
                    except (model.DoesNotExist, ValueError, TypeError, DjangoValidationError):
                        logger.info("Object pk=%s not found locally for %s, using RemoteObject fallback", object_id, model.__name__)
                        obj = RemoteObject(content_type=rd.content_type, object_id=object_id)

            # Validators not ran, because this should be an internal action

            if rd.content_type:
                # Object role assignment
                if not obj:
                    raise serializers.ValidationError({'object_id': _('Object must be specified for this role assignment')})

                check_content_obj_permission(requesting_user, obj)

                with transaction.atomic():
                    assignment = rd.give_permission(actor, obj)
            else:
                with transaction.atomic():
                    assignment = rd.give_global_permission(actor)

            return assignment


class ServiceRoleUserAssignmentSerializer(BaseAssignmentSerializer):
    user_ansible_id = ActorAnsibleIdField(source='user', required=True)
    actor_field = 'user'

    class Meta:
        model = RoleUserAssignment
        fields = assignment_common_fields + ('user_ansible_id',)
        validators = []  # DRF can't auto-generate validators for partial UniqueConstraints with aliased fields


class ServiceRoleTeamAssignmentSerializer(BaseAssignmentSerializer):
    team_ansible_id = ActorAnsibleIdField(source='team', required=True)
    actor_field = 'team'

    class Meta:
        model = RoleTeamAssignment
        fields = assignment_common_fields + ('team_ansible_id',)
        validators = []  # DRF can't auto-generate validators for partial UniqueConstraints with aliased fields
