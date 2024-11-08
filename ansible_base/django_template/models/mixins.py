from django.contrib.auth import get_user_model
from django.db.models import Model

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import ObjectRole, RoleDefinition


class UsersMembersMixin(Model):
    class Meta:
        abstract = True

    admin_rd_name = None
    member_rd_name = None

    def related_fields(self, request):
        ret = super().related_fields(request)
        for key in ('users', 'admins'):
            ret[key] = get_relative_url(f'{self._meta.model_name}-{key}-list', kwargs={'pk': self.id})
        return ret

    @property
    def member_rd(self):
        return RoleDefinition.objects.get(name=self.member_rd_name)

    @property
    def admin_rd(self):
        return RoleDefinition.objects.get(name=self.admin_rd_name)

    def add_member(self, user):
        self.member_rd.give_permission(user, self)

    def add_admin(self, user):
        self.admin_rd.give_permission(user, self)

    def remove_member(self, user):
        self.member_rd.remove_permission(user, self)

    def remove_admin(self, user):
        self.admin_rd.remove_permission(user, self)

    @property
    def admins(self):
        return get_user_model().objects.filter(has_roles__in=ObjectRole.objects.filter(object_id=self.pk, role_definition__name=self.admin_rd_name))

    @property
    def users(self):
        return get_user_model().objects.filter(has_roles__in=ObjectRole.objects.filter(object_id=self.pk, role_definition__name=self.member_rd_name))
