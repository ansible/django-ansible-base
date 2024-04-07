from django.conf import settings
from django.utils.translation import gettext_lazy as _
from rest_framework import permissions
from rest_framework.viewsets import ReadOnlyModelViewSet

from ansible_base.activitystream.models import Entry, FieldChange
from ansible_base.activitystream.serializers import EntrySerializer, FieldChangeSerializer
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView
from ansible_base.lib.utils.views.permissions import IsSuperuser


class EntryReadOnlyViewSet(ReadOnlyModelViewSet, AnsibleBaseDjangoAppApiView):
    """
    API endpoint that allows for read-only access to activity stream entries.
    """

    queryset = Entry.objects.all()
    serializer_class = EntrySerializer

    def get_permissions(self):
        """
        If the RBAC app is enabled, then we delegate to it to manage permissions.
        Otherwise, we require superuser status.
        """
        if 'ansible_base.rbac' in settings.INSTALLED_APPS:
            permission_classes = [permissions.IsAuthenticated]
        else:
            permission_classes = [IsSuperuser]
        return [permission() for permission in permission_classes]

    def get_view_name(self):
        return _('Activity Stream Entries')


class FieldChangeReadOnlyViewSet(ReadOnlyModelViewSet, AnsibleBaseDjangoAppApiView):
    """
    API endpoint that allows for read-only access to an activity stream entry's field changes.
    """

    queryset = FieldChange.objects.all()
    serializer_class = FieldChangeSerializer

    def get_permissions(self):
        """
        If the RBAC app is enabled, then we delegate to it to manage permissions.
        Otherwise, we require superuser status.
        """
        if 'ansible_base.rbac' in settings.INSTALLED_APPS:
            permission_classes = [permissions.IsAuthenticated]
        else:
            permission_classes = [IsSuperuser]
        return [permission() for permission in permission_classes]

    def get_view_name(self):
        return _('Activity Stream Entry Field Changes')
