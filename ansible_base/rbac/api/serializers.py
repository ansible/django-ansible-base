from typing import Optional

from django.apps import apps
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Model
from django.db.utils import IntegrityError
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.fields import flatten_choices_dict, to_choices_dict
from rest_framework.serializers import ValidationError

from ansible_base.lib.abstract_models.common import get_url_for_object
from ansible_base.lib.serializers.common import CommonModelSerializer, ImmutableCommonModelSerializer
from ansible_base.rbac.models import RoleDefinition, RoleTeamAssignment, RoleUserAssignment
from ansible_base.rbac.permission_registry import permission_registry  # careful for circular imports
from ansible_base.rbac.policies import check_content_obj_permission, visible_users
from ansible_base.rbac.validators import validate_permissions_for_model
from ansible_base.resource_registry.models import Resource


class ChoiceLikeMixin(serializers.ChoiceField):
    """
    This uses a ForeignKey to populate the choices of a choice field.
    This also manages some string manipulation, right now, adding the local service name.
    """

    default_error_messages = serializers.PrimaryKeyRelatedField.default_error_messages

    def get_dynamic_choices(self):
        raise NotImplementedError

    def get_dynamic_object(self, data):
        raise NotImplementedError

    def to_representation(self, value):
        raise NotImplementedError

    def __init__(self, **kwargs):
        # Workaround so that the parent class does not resolve the choices right away
        self.html_cutoff = kwargs.pop('html_cutoff', self.html_cutoff)
        self.html_cutoff_text = kwargs.pop('html_cutoff_text', self.html_cutoff_text)

        self.allow_blank = kwargs.pop('allow_blank', False)
        super(serializers.ChoiceField, self).__init__(**kwargs)

    def _initialize_choices(self):
        choices = self.get_dynamic_choices()
        self._grouped_choices = to_choices_dict(choices)
        self._choices = flatten_choices_dict(self._grouped_choices)
        self.choice_strings_to_values = {str(k): k for k in self._choices}

    @cached_property
    def grouped_choices(self):
        self._initialize_choices()
        return self._grouped_choices

    @cached_property
    def choices(self):
        self._initialize_choices()
        return self._choices

    def to_internal_value(self, data):
        try:
            return self.get_dynamic_object(data)
        except ObjectDoesNotExist:
            self.fail('does_not_exist', pk_value=data)
        except (TypeError, ValueError):
            self.fail('incorrect_type', data_type=type(data).__name__)


class ContentTypeField(ChoiceLikeMixin):

    def __init__(self, **kwargs):
        kwargs['help_text'] = _('The type of resource this applies to')
        super().__init__(**kwargs)

    def get_resource_type_name(self, cls) -> str:
        return f"{permission_registry.get_resource_prefix(cls)}.{cls._meta.model_name}"

    def get_dynamic_choices(self):
        return list(sorted((self.get_resource_type_name(cls), cls._meta.verbose_name.title()) for cls in permission_registry.all_registered_models))

    def get_dynamic_object(self, data):
        model = data.rsplit('.')[-1]
        return permission_registry.content_type_model.objects.get(model=model)

    def to_representation(self, value):
        if isinstance(value, str):
            return value  # slight hack to work to AWX schema tests
        return self.get_resource_type_name(value.model_class())


class PermissionField(ChoiceLikeMixin):
    @property
    def service_prefix(self):
        if registry := permission_registry.get_resource_registry():
            return registry.api_config.service_type
        return 'local'

    def get_dynamic_choices(self):
        perms = []
        for cls in permission_registry.all_registered_models:
            cls_name = cls._meta.model_name
            for action in cls._meta.default_permissions:
                perms.append(f'{permission_registry.get_resource_prefix(cls)}.{action}_{cls_name}')
            for perm_name, description in cls._meta.permissions:
                perms.append(f'{permission_registry.get_resource_prefix(cls)}.{perm_name}')
        return list(sorted(perms))

    def get_dynamic_object(self, data):
        codename = data.rsplit('.')[-1]
        return permission_registry.permission_qs.get(codename=codename)

    def to_representation(self, value):
        if isinstance(value, str):
            return value  # slight hack to work to AWX schema tests
        ct = permission_registry.content_type_model.objects.get_for_id(value.content_type_id)  # optimization
        return f'{permission_registry.get_resource_prefix(ct.model_class())}.{value.codename}'


class ManyRelatedListField(serializers.ListField):
    def to_representation(self, data):
        "Adds the .all() to treat the value as a queryset"
        return [self.child.to_representation(item) if item is not None else None for item in data.all()]


class RoleDefinitionSerializer(CommonModelSerializer):
    # Relational versions - we may switch to these if custom permission and type models are exposed but out of scope here
    # permissions = serializers.SlugRelatedField(many=True, slug_field='codename', queryset=DABPermission.objects.all())
    # content_type = ContentTypeField(slug_field='model', queryset=permission_registry.content_type_model.objects.all(), allow_null=True, default=None)
    permissions = ManyRelatedListField(child=PermissionField())
    content_type = ContentTypeField(allow_null=True, default=None)

    class Meta:
        model = RoleDefinition
        read_only_fields = ('id', 'summary_fields')
        fields = '__all__'

    def validate(self, validated_data):
        # Obtain the resultant new values
        if 'permissions' in validated_data:
            permissions = validated_data['permissions']
        else:
            permissions = list(self.instance.permissions.all())
        if 'content_type' in validated_data:
            content_type = validated_data['content_type']
        else:
            content_type = self.instance.content_type
        validate_permissions_for_model(permissions, content_type)
        return super().validate(validated_data)


class RoleDefinitionDetailSerializer(RoleDefinitionSerializer):
    content_type = ContentTypeField(read_only=True)


class BaseAssignmentSerializer(CommonModelSerializer):
    content_type = ContentTypeField(read_only=True)
    object_ansible_id = serializers.UUIDField(
        required=False,
        help_text=_('Deprecated, use the resource field instead.'),
    )
    resource = serializers.SlugRelatedField(
        slug_field='ansible_id',
        queryset=Resource.objects.all(),
        allow_null=True,
        required=False,
        help_text=_('Resource id of the object this role applies to. Alternative to the object_id field.'),
    )
    object_fields = ['object_id', 'object_ansible_id', 'resource']

    def __init__(self, *args, **kwargs):
        """
        We want to allow ansible_id override of user and team fields
        but want to keep the non-null database constraint, so actor field is marked required=True here
        """
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request:
            qs = self.get_actor_queryset(request.user)
        else:
            qs = self.Meta.model._meta.get_field(self.actor_field).model.objects.all()
        self.fields[self.actor_field] = serializers.PrimaryKeyRelatedField(queryset=qs, required=False)

    @property
    def actor_fields(self):
        return [self.actor_field, f'{self.actor_field}_ansible_id', f'{self.actor_field}_resource']

    def raise_id_fields_error(self, field_list: list[str]):
        msg = _('Provide exactly one of %(field_list)s') % {'field_list': field_list}
        raise ValidationError({field_name: msg for field_name in field_list})

    def raise_actor_fields_error(self):
        self.raise_id_fields_error(self.actor_fields)

    def raise_object_fields_error(self):
        self.raise_id_fields_error(self.object_fields)

    def get_by_ansible_id(self, ansible_id, requesting_user: Model, for_field: str) -> Model:
        """Uses ansible_id, deprecated"""
        try:
            resource_cls = apps.get_model('dab_resource_registry', 'Resource')
        except LookupError:
            raise ValidationError({for_field: _('Django-ansible-base resource registry must be installed to use ansible_id fields')})

        try:
            resource = resource_cls.objects.get(ansible_id=ansible_id)
            # Ensure that the request user has permission to view provided data
            obj = resource.content_object
            if obj._meta.model_name == 'user':
                if not visible_users(requesting_user).filter(pk=obj.pk).exists():
                    raise ObjectDoesNotExist
            elif not requesting_user.has_obj_perm(obj, 'view'):
                raise ObjectDoesNotExist
        except ObjectDoesNotExist:
            msg = serializers.PrimaryKeyRelatedField.default_error_messages['does_not_exist']
            raise ValidationError({for_field: msg.format(pk_value=ansible_id)})
        return obj

    def get_obj_from_resource(self, resource: Resource, requesting_user: Model, for_field: str) -> Model:
        """Return the content_object of the resource and check permissions"""
        try:
            # Ensure that the request user has permission to view provided data
            obj = resource.content_object
            if obj._meta.model_name == 'user':
                if not visible_users(requesting_user).filter(pk=obj.pk).exists():
                    raise ObjectDoesNotExist
            elif not requesting_user.has_obj_perm(obj, 'view'):
                raise ObjectDoesNotExist
        except ObjectDoesNotExist:
            msg = serializers.PrimaryKeyRelatedField.default_error_messages['does_not_exist']
            raise ValidationError({for_field: msg.format(pk_value=resource.ansible_id)})
        return obj

    def get_actor_from_data(self, validated_data: dict, requesting_user: Model) -> Model:
        """Return the user or team from validated request data, implicitly check read permission for request user"""
        actor_aid_field = f'{self.actor_field}_ansible_id'
        actor_resource_field = f'{self.actor_field}_resource'
        if len([field_name for field_name in self.actor_fields if validated_data.get(field_name)]) > 1:
            self.raise_actor_fields_error()
        elif validated_data.get(self.actor_field):
            actor = validated_data[self.actor_field]
        elif validated_data.get(actor_aid_field) or validated_data.get(actor_resource_field):
            if ansible_id := validated_data.get(actor_aid_field):
                actor = self.get_by_ansible_id(ansible_id, requesting_user, for_field=actor_aid_field)
            else:
                resource = validated_data[actor_resource_field]
                actor = self.get_obj_from_resource(resource, requesting_user, for_field=actor_resource_field)
        else:
            self.raise_actor_fields_error()
        return actor

    def get_object_from_data(self, validated_data, role_definition, requesting_user) -> Optional[Model]:
        """Return the content object specified by validated request data, implicitly check read permission for request user"""
        obj = None
        if len([field_name for field_name in self.object_fields if validated_data.get(field_name)]) > 1:
            self.raise_object_fields_error()
        elif validated_data.get('object_id'):
            if not role_definition.content_type:
                raise ValidationError({'object_id': _('System role does not allow for object assignment')})
            model = role_definition.content_type.model_class()
            try:
                obj = serializers.PrimaryKeyRelatedField(queryset=model.access_qs(requesting_user)).to_internal_value(validated_data['object_id'])
            except ValidationError as exc:
                raise ValidationError({'object_id': exc.detail})
        elif validated_data.get('object_ansible_id') or validated_data.get('resource'):
            if validated_data.get('object_ansible_id'):
                field_name = 'object_ansible_id'
                obj = self.get_by_ansible_id(validated_data.get('object_ansible_id'), requesting_user, for_field='object_ansible_id')
            else:
                field_name = 'resource'
                resource = validated_data['resource']
                obj = self.get_obj_from_resource(resource, requesting_user, for_field='resource')
            if permission_registry.content_type_model.objects.get_for_model(obj) != role_definition.content_type:
                raise ValidationError(
                    {
                        field_name: _('Object type of %(model_name)s does not match role type of %(role_definition)s')
                        % {'model_name': obj._meta.model_name, 'role_definition': role_definition.content_type.model}
                    }
                )
        return obj

    def create(self, validated_data):
        rd = validated_data['role_definition']
        requesting_user = self.context['view'].request.user

        # Resolve actor - team or user
        actor = self.get_actor_from_data(validated_data, requesting_user)

        # Resolve object
        obj = self.get_object_from_data(validated_data, rd, requesting_user)

        if rd.content_type:
            # Object role assignment
            if not obj:
                raise ValidationError({'object_id': _('Object must be specified for this role assignment')})

            check_content_obj_permission(requesting_user, obj)

            try:
                with transaction.atomic():
                    assignment = rd.give_permission(actor, obj)
            except IntegrityError:
                assignment = self.Meta.model.objects.get(role_definition=rd, object_id=obj.pk, **{self.actor_field: actor})
        else:
            # Global role assignment, only allowed by superuser
            if not requesting_user.is_superuser:
                raise PermissionDenied

            with transaction.atomic():
                assignment = rd.give_global_permission(actor)

        return assignment

    def _get_related(self, obj) -> dict[str, str]:
        related = super()._get_related(obj)
        content_obj = obj.content_object
        if content_obj:
            if related_url := get_url_for_object(content_obj):
                related['content_object'] = related_url
        return related

    def _get_summary_fields(self, obj) -> dict[str, dict]:
        summary_fields = super()._get_summary_fields(obj)
        content_obj = obj.content_object
        if content_obj and hasattr(content_obj, 'summary_fields'):
            summary_fields['content_object'] = content_obj.summary_fields()
        return summary_fields


ASSIGNMENT_FIELDS = ImmutableCommonModelSerializer.Meta.fields + ['content_type', 'object_id', 'object_ansible_id', 'resource', 'role_definition']


class RoleUserAssignmentSerializer(BaseAssignmentSerializer):
    actor_field = 'user'
    user_ansible_id = serializers.UUIDField(
        required=False,
        help_text=_('Deprecated, use the user_resource field instead.'),
    )
    user_resource = serializers.SlugRelatedField(
        slug_field='ansible_id',
        queryset=Resource.objects.filter(content_type__model='user'),
        allow_null=True,
        required=False,
        help_text=_('Resource id of the user who will receive permissions from this assignment. Alternative to user field.'),
    )

    class Meta:
        model = RoleUserAssignment
        fields = ASSIGNMENT_FIELDS + ['user', 'user_ansible_id', 'user_resource']

    def get_actor_queryset(self, requesting_user):
        return visible_users(requesting_user)


class RoleTeamAssignmentSerializer(BaseAssignmentSerializer):
    actor_field = 'team'
    team_ansible_id = serializers.UUIDField(
        required=False,
        help_text=_('Deprecated, use the team_resource field instead.'),
    )
    team_resource = serializers.SlugRelatedField(
        slug_field='ansible_id',
        queryset=Resource.objects.filter(content_type__model='team'),
        allow_null=True,
        required=False,
        help_text=_('Resource id of the team who will receive permissions from this assignment. Alternative to team field.'),
    )

    class Meta:
        model = RoleTeamAssignment
        fields = ASSIGNMENT_FIELDS + ['team', 'team_ansible_id', 'team_resource']

    def get_actor_queryset(self, requesting_user):
        return permission_registry.team_model.access_qs(requesting_user)


class RoleMetadataSerializer(serializers.Serializer):
    allowed_permissions = serializers.DictField(help_text=_('List of permissions allowed for a role definition, given its content type.'))
