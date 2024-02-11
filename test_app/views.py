from rest_framework import permissions
from rest_framework.viewsets import ModelViewSet

from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView
from test_app import serializers
from test_app.models import EncryptionModel, RelatedFieldsTestModel, Team, User


class TestAppViewSet(ModelViewSet, AnsibleBaseView):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return self.serializer_class.Meta.model.objects.all()


class OrganizationViewSet(TestAppViewSet):
    serializer_class = serializers.OrganizationSerializer


class TeamViewSet(TestAppViewSet):
    queryset = Team.objects.all()
    serializer_class = serializers.TeamSerializer


class UserViewSet(TestAppViewSet):
    queryset = User.objects.all()
    serializer_class = serializers.UserSerializer


class EncryptionModelViewSet(TestAppViewSet):
    queryset = EncryptionModel.objects.all()
    serializer_class = serializers.EncryptionTestSerializer


class RelatedFieldsTestModelViewSet(TestAppViewSet):
    queryset = RelatedFieldsTestModel.objects.all()  # needed to automatic basename from router
    serializer_class = serializers.RelatedFieldsTestModelSerializer
