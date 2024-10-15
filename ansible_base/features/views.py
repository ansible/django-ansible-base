from rest_framework import mixins
from rest_framework.viewsets import GenericViewSet

from ansible_base.features.models import Feature
from ansible_base.features.serializers import FeatureSerializer
from ansible_base.lib.utils.views.django_app_api import AnsibleBaseDjangoAppApiView


class FeatureViewSet(AnsibleBaseDjangoAppApiView, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, GenericViewSet):
    """
    API endpoint that allows features to be viewed and configured
    """

    queryset = Feature.objects.all()
    serializer_class = FeatureSerializer
