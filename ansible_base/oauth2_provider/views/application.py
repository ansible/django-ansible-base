from rest_framework import permissions
from rest_framework.viewsets import ModelViewSet

from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView
from ansible_base.oauth2_provider.models import OAuth2Application
from ansible_base.oauth2_provider.serializers import OAuth2ApplicationSerializer


class OAuth2ApplicationViewSet(AnsibleBaseDjangoAppApiView, ModelViewSet):
    queryset = OAuth2Application.objects.all()
    serializer_class = OAuth2ApplicationSerializer
    permission_classes = [permissions.IsAuthenticated]
