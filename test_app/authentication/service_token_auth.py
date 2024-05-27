import jwt
from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication, get_authorization_header

from ansible_base.lib.utils.models import get_system_user
from ansible_base.resource_registry.resource_server import get_resource_server_config

User = get_user_model()


class ServiceTokenAuthentication(BaseAuthentication):
    keyword = "Token"

    def authenticate(self, request):
        auth = get_authorization_header(request).split()

        if not auth or auth[0].lower() != self.keyword.lower().encode():
            return None

        token = auth[1]

        cfg = get_resource_server_config()

        try:
            data = jwt.decode(
                token,
                cfg["SECRET_KEY"],
                algorithms=cfg["JWT_ALGORITHM"],
                required=["iss", "exp"],
            )

            if "sub" in data:
                return (User.objects.get(resource__ansible_id=data["sub"]), None)
            else:
                return (get_system_user(), None)

        except jwt.exceptions.PyJWTError as e:
            print(e)
            return None
