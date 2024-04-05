from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _
from rest_framework.viewsets import ReadOnlyModelViewSet

from ansible_base.activitystream.models import Entry
from ansible_base.activitystream.serializers import EntrySerializer
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView


def _permission_classes():
    entry_permission_classes = []
    for cls in settings.ANSIBLE_BASE_ACTIVITYSTREAM_VIEW_PERMISSION_CLASSES:
        try:
            entry_permission_classes.append(import_string(cls))
        except ImportError as e:
            raise ImproperlyConfigured(f"[ANSIBLE_BASE_ACTIVITYSTREAM_VIEW_PERMISSION_CLASSES] Could not find permission class '{cls}'.") from e
    return entry_permission_classes


class EntryReadOnlyViewSet(ReadOnlyModelViewSet, AnsibleBaseDjangoAppApiView):
    """
    API endpoint that allows for read-only access to activity stream entries.
    """

    queryset = Entry.objects.all()
    serializer_class = EntrySerializer
    permission_classes = _permission_classes()

    def get_view_name(self):
        return _('Activity Stream Entries')
