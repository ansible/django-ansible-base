from rest_framework import permissions, serializers
from rest_framework.routers import SimpleRouter
from rest_framework.viewsets import ModelViewSet

from test_app.models import User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = '__all__'


class UserViewSet(ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]


router = SimpleRouter()

router.register(r'users', UserViewSet)
