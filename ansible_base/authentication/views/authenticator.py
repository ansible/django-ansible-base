import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from ansible_base.authentication.models import Authenticator, AuthenticatorUser
from ansible_base.authentication.serializers import AuthenticatorSerializer
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView

logger = logging.getLogger('ansible_base.authentication.views.authenticator')


class AuthenticatorViewSet(AnsibleBaseDjangoAppApiView, ModelViewSet):
    """
    API endpoint that allows authenticators to be viewed or edited.
    """

    queryset = Authenticator.objects.all()
    serializer_class = AuthenticatorSerializer

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        # check if there is at least one other enabled authenticator...
        if not Authenticator.objects.filter(enabled=True).exclude(id=instance.id).exists():
            logger.warning("Preventing deletion of last enabled authenticator")
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"details": "Authenticator cannot be deleted, as no authenticators would be enabled"})

        users_exist = AuthenticatorUser.objects.filter(provider_id=instance.slug).exists()
        if users_exist:
            logger.info("Found existing users from the authenticator")
            return Response(
                status=status.HTTP_409_CONFLICT, data={"details": "Authenticator cannot be deleted, as users from the authenticator exist in the system"}
            )
        else:
            logger.info(f"Deleting authenticator with ID={instance.id}")
            return super().destroy(request, *args, **kwargs)
