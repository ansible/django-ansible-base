from rest_framework import permissions
from rest_framework.routers import SimpleRouter
from rest_framework.viewsets import ModelViewSet

from test_app.models import User
from test_app.serializers import UserSerializer


class UserViewSet(ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]


router = SimpleRouter()

router.register(r'users', UserViewSet)
