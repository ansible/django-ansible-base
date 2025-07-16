from rest_framework.viewsets import ModelViewSet

from ansible_base.authentication.models import AuthenticatorMap
from ansible_base.authentication.serializers import AuthenticatorMapSerializer
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView


class AuthenticatorMapViewSet(AnsibleBaseDjangoAppApiView, ModelViewSet):
    """
    API endpoint that allows authenticator maps to be viewed or edited.
    """

    queryset = AuthenticatorMap.objects.all().order_by("id")
    serializer_class = AuthenticatorMapSerializer
    allow_service_token = True
