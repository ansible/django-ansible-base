from rest_framework import permissions
from rest_framework.viewsets import ModelViewSet

from ansible_base.authentication.models import AuthenticatorMap
from ansible_base.authentication.serializers import AuthenticatorMapSerializer


class AuthenticatorMapViewSet(ModelViewSet):
    """
    API endpoint that allows authenticator maps to be viewed or edited.
    """

    queryset = AuthenticatorMap.objects.all().order_by("id")
    serializer_class = AuthenticatorMapSerializer
    permission_classes = [permissions.IsAuthenticated]
