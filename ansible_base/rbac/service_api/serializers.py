from crum import impersonate
from django.apps import apps
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from ..api.fields import ActorAnsibleIdField
from ..models import DABContentType, DABPermission, RoleDefinition, RoleTeamAssignment, RoleUserAssignment
from ..remote import RemoteObject


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


class ObjectIDAnsibleIDField(serializers.Field):
    "This is an ansible_id field intended to be used with source pointing to object_id, so, does conversion"

    def to_representation(self, value):
        "The source for this field is object_id, which is ignored, use content_object instead"
        assignment = getattr(self, "_this_assignment", None)
        if not assignment:
            return None
        content_object = assignment.content_object
        if isinstance(content_object, RemoteObject):
            return None
        if hasattr(content_object, 'resource'):
            return str(content_object.resource.ansible_id)
        return None

    def to_internal_value(self, value):
        "Targeting object_id, this converts ansible_id into object_id"
        resource_cls = apps.get_model('dab_resource_registry', 'Resource')
        resource = resource_cls.objects.get(ansible_id=value)
        return resource.object_id


assignment_common_fields = ('created', 'created_by_ansible_id', 'object_id', 'object_ansible_id', 'content_type', 'role_definition')


class BaseAssignmentSerializer(serializers.ModelSerializer):
    content_type = serializers.SlugRelatedField(read_only=True, slug_field='api_slug')
    role_definition = serializers.SlugRelatedField(slug_field='name', queryset=RoleDefinition.objects.all())
    created_by_ansible_id = ActorAnsibleIdField(source='created_by', required=False, allow_null=True)
    object_ansible_id = ObjectIDAnsibleIDField(source='object_id', required=False, allow_null=True)
    object_id = serializers.CharField(allow_blank=True, required=False, allow_null=True)
    from_service = serializers.CharField(write_only=True)

    def to_representation(self, instance):
        # hack to surface content_object for ObjectIDAnsibleIDField
        self.fields["object_ansible_id"]._this_assignment = instance
        return super().to_representation(instance)

    def get_created_by_ansible_id(self, obj):
        return str(obj.created_by.resource.ansible_id)

    def validate(self, attrs):
        """The object_id vs ansible_id is the only dual-write case, where we have to accept either

        So this does the mutual validation to assure we have sufficient data.
        """
        has_oid = bool(self.initial_data.get('object_id'))
        has_oaid = bool(self.initial_data.get('object_ansible_id'))

        rd = attrs['role_definition']
        if rd.content_type_id:
            if not self.partial and not has_oid and not has_oaid:
                raise serializers.ValidationError("You must provide either 'object_id' or 'object_ansible_id'.")
            elif not has_oaid:
                # need to remove blank and null fields or else it can overwrite the non-null non-blank field
                attrs['object_id'] = self.initial_data['object_id']
        else:
            if has_oaid or has_oid:
                raise serializers.ValidationError("Can not provide either 'object_id' or 'object_ansible_id' for system role")

        # NOTE: right now not enforcing the case you provide both, could check for consistency later

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
                    except model.DoesNotExist as exc:
                        raise serializers.ValidationError({'object_id': str(exc)})

            # Validators not ran, because this should be an internal action

            if rd.content_type:
                # Object role assignment
                if not obj:
                    raise serializers.ValidationError({'object_id': _('Object must be specified for this role assignment')})

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


class ServiceRoleTeamAssignmentSerializer(BaseAssignmentSerializer):
    team_ansible_id = ActorAnsibleIdField(source='team', required=True)
    actor_field = 'team'

    class Meta:
        model = RoleTeamAssignment
        fields = assignment_common_fields + ('team_ansible_id',)
