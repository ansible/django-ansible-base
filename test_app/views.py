from rest_framework import permissions
from rest_framework.viewsets import ModelViewSet

from test_app import serializers
from test_app.models import RelatedFieldsTestModel


class TestAppViewSet(ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return self.serializer_class.Meta.model.objects.all()


class OrganizationViewSet(TestAppViewSet):
    serializer_class = serializers.OrganizationSerializer


class TeamViewSet(TestAppViewSet):
    serializer_class = serializers.TeamSerializer


class UserViewSet(TestAppViewSet):
    serializer_class = serializers.UserSerializer


class EncryptionModelViewSet(TestAppViewSet):
    serializer_class = serializers.EncryptionTestSerializer


class RelatedFieldsTestModelViewSet(TestAppViewSet):
    queryset = RelatedFieldsTestModel.objects.all()  # needed to automatic basename from router
    serializer_class = serializers.RelatedFieldsTestModelSerializer
