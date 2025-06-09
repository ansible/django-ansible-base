from django.conf import settings
from django.utils.translation import gettext_lazy as _
from rest_framework.viewsets import ReadOnlyModelViewSet

from ansible_base.activitystream.filtering import ActivityStreamFilterBackend
from ansible_base.activitystream.models import Entry
from ansible_base.activitystream.serializers import EntrySerializer
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView
from ansible_base.lib.utils.views.permissions import IsSuperuser


def calculate_filter_backends():
    """
    Calculate the filter backends for the Activity Stream.

    We want to use the ActivityStreamFilterBackend for the FieldLookupBackend, but we want to keep the
    default filter backends (in order) for everything else.
    """
    default_filter_backends = AnsibleBaseDjangoAppApiView.filter_backends
    filter_backends = []
    added_activity_stream_backend = False
    for backend in default_filter_backends:
        if backend.__name__ == 'FieldLookupBackend':
            filter_backends.append(ActivityStreamFilterBackend)
            added_activity_stream_backend = True
        else:
            filter_backends.append(backend)

    if not added_activity_stream_backend:
        filter_backends.append(ActivityStreamFilterBackend)

    return filter_backends


class EntryReadOnlyViewSet(ReadOnlyModelViewSet, AnsibleBaseDjangoAppApiView):
    """
    API endpoint that allows for read-only access to activity stream entries.
    """

    queryset = Entry.objects.all()
    serializer_class = EntrySerializer
    filter_backends = calculate_filter_backends()
    ordering = ['-id']

    def get_permissions(self):
        """
        If the RBAC app is enabled, then we delegate to it to manage permissions.
        Otherwise, we require superuser status.
        """
        if 'ansible_base.rbac' in settings.INSTALLED_APPS:
            # TODO: permission_classes = [AnsibleBaseObjectPermissions] is not applicable now,
            #  set to default permission class
            return super().get_permissions()
        else:
            permission_classes = [IsSuperuser]
        return [permission() for permission in permission_classes]

    def get_view_name(self):
        return _('Activity Stream Entries')
