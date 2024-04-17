from django.apps import apps
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
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
from ansible_base.rbac.policies import check_content_obj_permission
from ansible_base.rbac.validators import validate_permissions_for_model


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

    def get_resource_registry(self):
        if 'ansible_base.resource_registry' not in settings.INSTALLED_APPS:
            return None

        from ansible_base.resource_registry.registry import get_registry

        return get_registry()


class ContentTypeField(ChoiceLikeMixin):

    def __init__(self, **kwargs):
        kwargs['help_text'] = _('The type of resource this applies to')
        super().__init__(**kwargs)

    def get_resource_type_name(self, cls) -> str:
        if registry := self.get_resource_registry():
            # duplicates logic in ansible_base/resource_registry/apps.py
            try:
                resource_config = registry.get_config_for_model(cls)
                if serializer := resource_config.managed_serializer:
                    return f"shared.{serializer.RESOURCE_TYPE}"  # shared model
            except KeyError:
                pass  # unregistered model

            # Fallback for unregistered and non-shared models
            return f"{registry.api_config.service_type}.{cls._meta.model_name}"
        else:
            return f'aap.{cls._meta.model_name}'

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
        if registry := self.get_resource_registry():
            return registry.api_config.service_type
        return 'local'

    def get_dynamic_choices(self):
        perms = []
        for cls in permission_registry.all_registered_models:
            cls_name = cls._meta.model_name
            for action in cls._meta.default_permissions:
                perms.append(f'{self.service_prefix}.{action}_{cls_name}')
            for perm_name, description in cls._meta.permissions:
                perms.append(f'{self.service_prefix}.{perm_name}')
        return list(sorted(perms))

    def get_dynamic_object(self, data):
        codename = data.rsplit('.')[-1]
        return permission_registry.permission_qs.get(codename=codename)

    def to_representation(self, value):
        if isinstance(value, str):
            return value  # slight hack to work to AWX schema tests
        return f'{self.service_prefix}.{value.codename}'


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
        help_text=_('Resource id of the object this role applies to. Alternative to the object_id field.'),
    )

    def get_fields(self):
        """
        We want to allow ansible_id override of user and team fields
        but want to keep the non-null database constraint, which leads to this solution
        """
        fields = dict(super().get_fields())
        fields[self.actor_field].required = False
        return fields

    def raise_id_fields_error(self, field1, field2):
        msg = _('Provide exactly one of %(actor_field)s or %(actor_field)s_ansible_id') % {'actor_field': self.actor_field}
        raise ValidationError({self.actor_field: msg, f'{self.actor_field}_ansible_id': msg})

    def get_by_ansible_id(self, ansible_id, requesting_user, for_field):
        try:
            resource_cls = apps.get_model('dab_resource_registry', 'Resource')
        except LookupError:
            raise ValidationError({for_field: _('Django-ansible-base resource registry must be installed to use ansible_id fields')})

        try:
            resource = resource_cls.access_qs(requesting_user).get(ansible_id=ansible_id)
        except ObjectDoesNotExist:
            msg = serializers.PrimaryKeyRelatedField.default_error_messages['does_not_exist']
            raise ValidationError({for_field: msg.format(pk_value=ansible_id)})
        return resource.content_object

    def get_actor_from_data(self, validated_data, requesting_user):
        actor_aid_field = f'{self.actor_field}_ansible_id'
        if validated_data.get(self.actor_field) and validated_data.get(actor_aid_field):
            self.raise_id_fields_error(self.actor_field, actor_aid_field)
        elif validated_data.get(self.actor_field):
            actor = validated_data[self.actor_field]
        elif ansible_id := validated_data.get(actor_aid_field):
            actor = self.get_by_ansible_id(ansible_id, requesting_user, for_field=actor_aid_field)
        else:
            self.raise_id_fields_error(self.actor_field, f'{self.actor_field}_ansible_id')
        return actor

    def get_object_from_data(self, validated_data, role_definition, requesting_user):
        obj = None
        if validated_data.get('object_id') and validated_data.get('object_ansible_id'):
            self.raise_id_fields_error('object_id', 'object_ansible_id')
        elif validated_data.get('object_id'):
            if not role_definition.content_type:
                raise ValidationError({'object_id': _('System role does not allow for object assignment')})
            model = role_definition.content_type.model_class()
            try:
                obj = serializers.PrimaryKeyRelatedField(queryset=model.access_qs(requesting_user)).to_internal_value(validated_data['object_id'])
            except ValidationError as exc:
                raise ValidationError({'object_id': exc.detail})
        elif validated_data.get('object_ansible_id'):
            obj = self.get_by_ansible_id(validated_data.get('object_ansible_id'), for_field='object_ansible_id')
            if permission_registry.content_type_model.objects.get_for_model(obj) != role_definition.content_type:
                raise ValidationError(
                    {
                        'object_ansible_id': _('Object type of %(model_name)s does not match role type of %(role_definition)s')
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


ASSIGNMENT_FIELDS = ImmutableCommonModelSerializer.Meta.fields + ['content_type', 'object_id', 'object_ansible_id', 'role_definition']


class RoleUserAssignmentSerializer(BaseAssignmentSerializer):
    actor_field = 'user'
    user_ansible_id = serializers.UUIDField(
        required=False,
        help_text=_('Resource id of the user who will receive permissions from this assignment. Alternative to user field.'),
    )

    class Meta:
        model = RoleUserAssignment
        fields = ASSIGNMENT_FIELDS + ['user', 'user_ansible_id']


class RoleTeamAssignmentSerializer(BaseAssignmentSerializer):
    actor_field = 'team'
    team_ansible_id = serializers.UUIDField(
        required=False,
        help_text=_('Resource id of the team who will receive permissions from this assignment. Alternative to team field.'),
    )

    class Meta:
        model = RoleTeamAssignment
        fields = ASSIGNMENT_FIELDS + ['team', 'team_ansible_id']
