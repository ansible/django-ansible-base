from django.utils.translation import gettext_lazy as _
from rest_framework import permissions
from rest_framework.viewsets import ReadOnlyModelViewSet

from ansible_base.activitystream.models import Entry
from ansible_base.activitystream.serializers import EntrySerializer
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView


class EntryReadOnlyViewSet(ReadOnlyModelViewSet, AnsibleBaseDjangoAppApiView):
    """
    API endpoint that allows for read-only access to activity stream entries.
    """

    queryset = Entry.objects.all()
    serializer_class = EntrySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_view_name(self):
        return _('Activity Stream Entries')
