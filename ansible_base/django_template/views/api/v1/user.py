from django.contrib.auth import get_user_model

from ansible_base.django_template.serializers import UserSerializer
from ansible_base.django_template.views.api.v1.common import TemplatedAppModelViewSet
from ansible_base.rbac.api.permissions import AnsibleBaseUserPermissions
from ansible_base.rbac.policies import can_view_all_users, visible_users


class UserViewSet(TemplatedAppModelViewSet):
    """
    API endpoint that allows users to be viewed or edited.
    """

    model = get_user_model()
    queryset = get_user_model().objects.select_related("resource").all()
    serializer_class = UserSerializer
    permission_classes = [AnsibleBaseUserPermissions]

    def filter_queryset(self, qs):
        qs = visible_users(self.request.user, queryset=qs)
        return super().filter_queryset(qs)

    def get_queryset(self):
        if self.detail:
            return get_user_model().all_objects.select_related("resource").all()
        return super().get_queryset()


class DeprecatedRelatedUserViewSet(TemplatedAppModelViewSet):
    """
    Shows all users for sublists like /api/v1/organizations/5/users/
    the related view still checks organization view permission
    """

    deprecated = True
    model = get_user_model()
    queryset = get_user_model().objects.select_related("resource").all()
    serializer_class = UserSerializer
    permission_classes = [AnsibleBaseUserPermissions]

    # Methods for compatibility with the old users and admins endpoints
    def get_association_role_definition(self, parent_instance):
        rd = None
        if self.association_fk == 'users':
            rd = parent_instance.member_rd
        elif self.association_fk == 'admins':
            rd = parent_instance.admin_rd
        return rd

    def get_sublist_queryset(self, parent_instance):
        rd = self.get_association_role_definition(parent_instance)
        object_roles = rd.object_roles.filter(object_id=parent_instance.pk)
        return self.queryset.filter(has_roles__in=object_roles)

    def perform_associate(self, parent_instance, related_instances):
        rd = self.get_association_role_definition(parent_instance)
        for user in related_instances:
            rd.give_permission(user, parent_instance)

    def perform_disassociate(self, parent_instance, related_instances):
        rd = self.get_association_role_definition(parent_instance)
        for user in related_instances:
            rd.remove_permission(user, parent_instance)


class OrganizationRelatedUserViewSet(DeprecatedRelatedUserViewSet):
    def filter_queryset(self, qs):
        qs = visible_users(self.request.user, queryset=qs, always_show_superusers=False, always_show_self=False)
        return super().filter_queryset(qs)


class TeamRelatedUserViewSet(DeprecatedRelatedUserViewSet):
    def filter_associate_queryset(self, qs):
        qs = visible_users(self.request.user, queryset=qs, always_show_superusers=False, always_show_self=False)
        return super().filter_queryset(qs)

    def is_team_admin(self, parent_instance):
        return self.request.user.has_obj_perm(parent_instance, 'change')

    def get_sublist_queryset(self, parent_instance):
        queryset = super().get_sublist_queryset(parent_instance)
        if can_view_all_users(self.request.user) or self.is_team_admin(parent_instance):
            return queryset
        return queryset & self.queryset.filter(pk=self.request.user.id)
