from rest_framework.routers import SimpleRouter

from ansible_base.authentication.views.authenticator import AuthenticatorViewSet
from ansible_base.authentication.views.authenticator_map import AuthenticatorMapViewSet


authentication_router = SimpleRouter()

authentication_router.register(r'authenticators', AuthenticatorViewSet, basename='authenticator')
authentication_router.register(r'authenticator_maps', AuthenticatorMapViewSet, basename='authenticator_map')
