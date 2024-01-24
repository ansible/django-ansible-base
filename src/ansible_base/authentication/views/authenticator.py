import logging

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from ansible_base.authentication.models import Authenticator, AuthenticatorMap, AuthenticatorUser
from ansible_base.authentication.serializers import AuthenticatorMapSerializer, AuthenticatorSerializer

logger = logging.getLogger('ansible_base.authentication.views.authenticator')


class AuthenticatorViewSet(ModelViewSet):
    """
    API endpoint that allows authenticators to be viewed or edited.
    """

    queryset = Authenticator.objects.all()
    serializer_class = AuthenticatorSerializer
    permission_classes = [permissions.IsAuthenticated]

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        users_exist = AuthenticatorUser.objects.filter(provider_id=instance.slug).exists()
        if users_exist:
            logger.info("Found existing users from the authenticator")
            return Response(
                status=status.HTTP_409_CONFLICT, data={"details": "Authenticator cannot be deleted, as users from the authenticator exist in the system"}
            )
        else:
            logger.info(f"Deleting authenticator with ID={instance.id}")
            return super().destroy(request, *args, **kwargs)


class AuthenticatorAuthenticatorMapViewSet(ModelViewSet):
    serializer_class = AuthenticatorMapSerializer

    def get_queryset(self):
        return AuthenticatorMap.objects.filter(authenticator=self.kwargs['pk']).order_by("order")
