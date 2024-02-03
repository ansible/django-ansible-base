from rest_framework.routers import SimpleRouter

from test_app import views

router = SimpleRouter()

router.register(r'organizations', views.UserViewSet, basename='organization')
router.register(r'teams', views.TeamViewSet, basename='team')
router.register(r'users', views.UserViewSet, basename='user')
# using an intentionally unpredictable basename
router.register(r'encrypted_models', views.EncryptionModelViewSet, basename='encryption_test_model')
