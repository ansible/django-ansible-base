#  Copyright 2024 Red Hat, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import logging
from urllib.parse import urljoin, urlparse

import jwt
import requests
from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from ansible_base.lib.utils.settings import get_setting

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

        if created:
            logger.warn(f"New user {user.username} created from JWT auth")
        else:
            logger.info(f"User {user.username} authenticated from JWT auth")

        return user, validated_body

    def log_and_raise(self, details):
        logger.error(details)
        raise AuthenticationFailed(details)

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
                self.log_and_raise(f"Failed to get 200 response from the issuer: {response.status_code}")
            return response.text
        except requests.exceptions.ConnectionError as e:
            self.log_and_raise(f"Failed to connect to {jwt_key_url}: {e}")
        except requests.exceptions.Timeout:
            self.log_and_raise(f"Timed out after {timeout} secs when connecting to {jwt_key_url}")
        except requests.exceptions.RequestException as e:
            self.log_and_raise(f"Failed to get JWT decryption key from JWT server: ({e.__class__.__name__}) {e}")

    def get_decryption_key_from_file(self, file_path):
        logger.debug(f"Loading decryption key from file {file_path}")

        try:
            with open(file_path, "r") as f:
                cert = f.read()
            return cert
        except FileNotFoundError:
            self.log_and_raise(f"The specified file {file_path} does not exist")
        except IsADirectoryError:
            self.log_and_raise(f"The specified file {file_path} is not a file")
        except PermissionError:
            self.log_and_raise(f"Permission error when reading {file_path}")
        except Exception as e:
            self.log_and_raise(f"Failed reading {file_path}: {e}")

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
            self.log_and_raise(f"Unable to determine how to handle {url_or_string} to get key")
        elif not key.startswith('-----BEGIN PUBLIC KEY-----') and not key.endswith('-----END PUBLIC KEY-----'):
            logger.debug(key)
            self.log_and_raise("Returned key does not start and end with BEGIN/END PUBLIC KEY")
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
            self.log_and_raise(f"JWT decoding failed: {e}, check your key and generated token")
        except jwt.exceptions.ExpiredSignatureError:
            self.log_and_raise("JWT has expired")
        except jwt.exceptions.InvalidAudienceError:
            self.log_and_raise("JWT did not come for the correct audience")
        except jwt.exceptions.InvalidIssuerError:
            self.log_and_raise("JWT did not come from the correct issuer")
        except jwt.exceptions.MissingRequiredClaimError as e:
            self.log_and_raise(f"Failed to decrypt JWT: {e}")
        except Exception as e:
            self.log_and_raise(f"Unknown error occurred decrypting JWT ({e.__class__}) {e}")

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
