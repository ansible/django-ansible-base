from django.contrib.auth import get_user_model
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from templated_app.serializers import UserSerializer
from templated_app.views.api.v1.common import AnsibleBaseView

User = get_user_model()


class MeViewSet(viewsets.ReadOnlyModelViewSet, AnsibleBaseView):
    model = User
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return User.objects.filter(username=self.request.user.username)
