from rest_framework import permissions
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.viewsets import ModelViewSet

from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView
from test_app import serializers
from test_app.models import RelatedFieldsTestModel


class TestAppViewSet(ModelViewSet, AnsibleBaseView):
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
    queryset = RelatedFieldsTestModel.objects.all()  # needed for automatic basename from router
    serializer_class = serializers.RelatedFieldsTestModelSerializer


# create api root view from the router
@api_view(['GET'])
def api_root(request, format=None):
    from test_app.router import router

    list_endpoints = {}
    for url in router.urls:
        # only want "root" list views, for example:
        # want '^users/$' [name='user-list']
        # do not want '^users/(?P<pk>[^/.]+)/organizations/$' [name='user-organizations-list'],
        if '-list' in url.name and url.pattern._regex.count('/') == 1:
            list_endpoints[url.name.removesuffix('-list')] = reverse(url.name, request=request, format=format)
    return Response(list_endpoints)
