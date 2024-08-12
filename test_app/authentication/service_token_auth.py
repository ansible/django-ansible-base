import jwt
from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication

from ansible_base.lib.utils.auth import get_user_by_ansible_id
from ansible_base.lib.utils.models import get_system_user
from ansible_base.resource_registry.resource_server import get_resource_server_config

User = get_user_model()


class ServiceTokenAuthentication(BaseAuthentication):
    keyword = "Token"

    def authenticate(self, request):
        token = request.headers.get("X-ANSIBLE-SERVICE-AUTH", None)

        if token is None:
            return None

        cfg = get_resource_server_config()

        try:
            data = jwt.decode(
                token,
                cfg["SECRET_KEY"],
                algorithms=cfg["JWT_ALGORITHM"],
                required=["iss", "exp"],
            )

            if "sub" in data:
                return (get_user_by_ansible_id(data["sub"]), None)
            else:
                return (get_system_user(), None)

        except jwt.exceptions.PyJWTError as e:
            print(e)
            return None
