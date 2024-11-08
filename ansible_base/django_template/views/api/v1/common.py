from rest_framework import viewsets

from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView
from ansible_base.lib.utils.views.permissions import IsSuperuserOrAuditor
from ansible_base.rbac.api.permissions import AnsibleBaseObjectPermissions


class TemplatedAppReadOnlyModelViewSet(viewsets.ReadOnlyModelViewSet, AnsibleBaseView):
    permission_classes = [IsSuperuserOrAuditor]


class TemplatedAppModelViewSet(viewsets.ModelViewSet, AnsibleBaseView):
    permission_classes = [IsSuperuserOrAuditor]


class RoleModelViewSet(TemplatedAppModelViewSet):
    "Use for models registered in the DAB RBAC permission registry"
    permission_classes = [AnsibleBaseObjectPermissions]

    def filter_queryset(self, qs):
        if hasattr(qs, 'model'):
            cls = qs.model
            qs = cls.access_qs(self.request.user, queryset=qs)

        return super().filter_queryset(qs)
