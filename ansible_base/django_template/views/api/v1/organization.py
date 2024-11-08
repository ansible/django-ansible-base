import logging

from django.utils.translation import gettext_lazy as _
from rest_framework import status
from rest_framework.response import Response

from ansible_base.django_template.serializers import OrganizationSerializer
from ansible_base.django_template.views.api.v1.common import RoleModelViewSet
from ansible_base.lib.utils.auth import get_organization_model

logger = logging.getLogger('aap.templated_app.views.organization')


class OrganizationViewSet(RoleModelViewSet):
    """
    API endpoint that allows organizations to be viewed or edited.
    """

    queryset = get_organization_model().objects.select_related("resource").all()
    serializer_class = OrganizationSerializer

    # Don't allow the deletion of any managed organizations
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.managed:
            logger.info("Managed organizations cannot be deleted.")
            return Response(status=status.HTTP_400_BAD_REQUEST, data={"details": _("Managed organizations cannot be deleted.")})
        else:
            return super().destroy(request, *args, **kwargs)
