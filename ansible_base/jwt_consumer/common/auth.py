import logging
from urllib.parse import urljoin, urlparse

import jwt
import requests
from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from ansible_base.lib.utils.settings import get_setting
from ansible_base.lib.utils.translations import translatableConditionally as _

logger = logging.getLogger("ansible_base.jwt_consumer.common.auth")


# These fields are used to both map the user as well as to validate the JWT token
default_mapped_user_fields = [
    "first_name",
    "last_name",
    "email",
    "is_superuser",
    "is_system_auditor",
]


class JWTCommonAuth:
    def __init__(self, user_fields=default_mapped_user_fields) -> None:
        self.mapped_user_fields = user_fields

    def parse_jwt_token(self, request):
        logger.debug("Starting JWT Authentication")
        token = request.headers.get("X-DAB-JW-TOKEN", None)
        if not token:
            logger.info("X-DAB-JW-TOKEN header not set for JWT authentication")
            return None, None
        logger.debug(f"Received JWT auth token: {token}")

        jwt_key_setting = get_setting("ANSIBLE_BASE_JWT_KEY")
        if not jwt_key_setting:
            logger.info("Failed to get the setting ANSIBLE_BASE_JWT_KEY")
            return None, None

        decryption_key = self.get_decryption_key(
            jwt_key_setting,
            validate_certs=get_setting("ANSIBLE_BASE_JWT_VALIDATE_CERT", True),
            timeout=get_setting("ANSIBLE_BASE_JWT_URL_TIMEOUT", 30),
        )
        validated_body = self.validate_token(token, decryption_key)
        user_model = get_user_model()
        user, created = user_model.objects.update_or_create(
            username=validated_body["sub"],
            defaults={
                "first_name": validated_body["first_name"],
                "last_name": validated_body["last_name"],
                "email": validated_body["email"],
                "is_superuser": validated_body["is_superuser"],
            },
        )
        setattr(user, "resource_api_actions", validated_body.get("resource_api_actions", None))
        if created:
            logger.warn(f"New user {user.username} created from JWT auth")
        else:
            logger.info(f"User {user.username} authenticated from JWT auth")

        return user, validated_body

    def log_and_raise(self, conditional_translate_object, expand_values={}):
        logger.error(conditional_translate_object.not_translated() % expand_values)
        raise AuthenticationFailed(conditional_translate_object.translated() % expand_values)

    def get_decryption_key_from_url(self, url, timeout, validate_certs):
        # If the URL does not end with / the urljoin will wipe out the existing path
        if not url.endswith('/'):
            url = f"{url}/"
        jwt_key_url = urljoin(url, "api/gateway/v1/jwt_key/")

        logger.debug(f"Loading decryption key from url {jwt_key_url}")

        try:
            response = requests.get(
                jwt_key_url,
                verify=validate_certs,
                timeout=timeout,
            )
            if response.status_code != 200:
                self.log_and_raise(_("Failed to get 200 response from the issuer: %(status_code)s"), {"status_code": response.status_code})
            return response.text
        except requests.exceptions.ConnectionError as e:
            self.log_and_raise(_("Failed to connect to %(jwt_key_url)s: %(e)s"), {"jwt_key_url": jwt_key_url, "e": e})
        except requests.exceptions.Timeout:
            self.log_and_raise(_("Timed out after %(timeout)s secs when connecting to %(jwt_key_url)s"), {"timeout": timeout, "jwt_key_url": jwt_key_url})
        except requests.exceptions.RequestException as e:
            self.log_and_raise(_("Failed to get JWT decryption key from JWT server: (%(e_class_name)s) %(e)s"), {"e_class_name": e.__class__.__name__, "e": e})

    def get_decryption_key_from_file(self, file_path):
        logger.debug(f"Loading decryption key from file {file_path}")

        try:
            with open(file_path, "r") as f:
                cert = f.read()
            return cert
        except FileNotFoundError:
            self.log_and_raise(_("The specified file %(file_path)s does not exist"), {"file_path": file_path})
        except IsADirectoryError:
            self.log_and_raise(_("The specified file %(file_path)s is not a file"), {"file_path": file_path})
        except PermissionError:
            self.log_and_raise(_("Permission error when reading %(file_path)s"), {"file_path": file_path})
        except Exception as e:
            self.log_and_raise(_("Failed reading %(file_path)s: %(e)s"), {"file_path": file_path, "e": e})

    def get_decryption_key(self, url_or_string, **kwargs):
        timeout = kwargs.get('timeout', 30)
        validate_certs = kwargs.get('validate_certs', True)
        url_info = urlparse(url_or_string)
        key = None
        logger.info(f"Loading decryption key from {url_or_string} scheme {url_info.scheme}")
        if url_info.scheme in ["http", "https"]:
            key = self.get_decryption_key_from_url(url_or_string, timeout, validate_certs)
        elif url_info.scheme == "file":
            file_path = url_info.path
            key = self.get_decryption_key_from_file(file_path)
        elif url_info.scheme == "" and url_info.path != "":
            logger.debug("Assuming decryption key is the actual cert")
            key = url_or_string

        if key is None:
            self.log_and_raise(_("Unable to determine how to handle %(url_or_string)s to get key"), {"url_or_string": url_or_string})
        elif not key.startswith('-----BEGIN PUBLIC KEY-----') and not key.endswith('-----END PUBLIC KEY-----'):
            logger.debug(key)
            self.log_and_raise(_("Returned key does not start and end with BEGIN/END PUBLIC KEY"))
        logger.info("Decryption key appears valid")
        logger.debug(f"{key}")
        return key

    def map_user_fields(self, user, token):
        user_needs_save = False
        for attribute in self.mapped_user_fields:
            old_value = getattr(user, attribute, None)
            new_value = token.get(attribute, None)
            if old_value != new_value:
                logger.debug(f"Changing {attribute} for {user.username} from {old_value} to {new_value}")
                setattr(user, attribute, new_value)
                user_needs_save = True
        if user_needs_save:
            logger.info(f"Saving user {user.username}")
            user.save()

    def validate_token(self, token, decryption_key):
        validated_body = None
        required_fields = self.mapped_user_fields

        # Ensure all of the internal pieces are part of the token but we don't want them in required_feidls or we will attempt to make them into the user object
        local_required_field = ["sub", "claims", "exp"]
        for field in required_fields:
            if field not in local_required_field:
                local_required_field.append(field)

        # Decrypt the token
        try:
            logger.info("Decrypting token")
            validated_body = jwt.decode(
                token,
                decryption_key,
                audience="ansible-services",
                options={"require": local_required_field},
                issuer="ansible-issuer",
                algorithms=["RS256"],
            )
        except jwt.exceptions.DecodeError as e:
            self.log_and_raise(_("JWT decoding failed: %(e)s, check your key and generated token"), {"e": e})
        except jwt.exceptions.ExpiredSignatureError:
            self.log_and_raise(_("JWT has expired"))
        except jwt.exceptions.InvalidAudienceError:
            self.log_and_raise(_("JWT did not come for the correct audience"))
        except jwt.exceptions.InvalidIssuerError:
            self.log_and_raise(_("JWT did not come from the correct issuer"))
        except jwt.exceptions.MissingRequiredClaimError as e:
            self.log_and_raise(_("Failed to decrypt JWT: %(e)s"), {"e": e})
        except Exception as e:
            self.log_and_raise(_("Unknown error occurred decrypting JWT (%(e_class)s) %(e)s"), {"e_class": e.__class__, "e": e})

        logger.debug(validated_body)

        return validated_body


class JWTAuthentication(BaseAuthentication):
    map_fields = default_mapped_user_fields

    def authenticate(self, request):
        common_auth = JWTCommonAuth(self.map_fields)
        user, token = common_auth.parse_jwt_token(request)

        if user:
            self.process_user_data(user, token)
            self.process_permissions(user, token.get("claims", None), token)

            return user, None
        else:
            return None

    def process_user_data(self, user, token):
        common_auth = JWTCommonAuth(self.map_fields)
        common_auth.map_user_fields(user, token)

    def process_permissions(self, user, claims, token):
        logger.info("process_permissions was not overridden for JWTAuthentication")
