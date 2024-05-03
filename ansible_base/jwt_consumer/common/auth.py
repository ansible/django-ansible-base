import logging
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse

import jwt
import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import caches
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
# This setting allows a service to override which django cache we want to use
jwt_cache_name = getattr(settings, 'ANSIBLE_BASE_JWT_CACHE_NAME', 'default')
cache = caches[jwt_cache_name]
# This is the cache name we will use for the JWT key
cache_key = 'ansible_base_jwt_public_key'


class JWTCommonAuth:
    def __init__(self, user_fields=default_mapped_user_fields) -> None:
        self.mapped_user_fields = user_fields

    def get_cache_timeout(self):
        # If unspecified the cache will expire in 7 days
        cache_timeout = get_setting('ANSIBLE_BASE_JWT_CACHE_TIMEOUT_SECONDS', 604800)
        return cache_timeout

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

        decryption_key, jwt_key_was_cached = self.get_decryption_key(
            jwt_key_setting,
            validate_certs=get_setting("ANSIBLE_BASE_JWT_VALIDATE_CERT", True),
            timeout=get_setting("ANSIBLE_BASE_JWT_URL_TIMEOUT", 30),
        )
        try:
            validated_body = self.validate_token(token, decryption_key)
        except jwt.exceptions.DecodeError as de:
            # This exception means the decryption key failed... maybe it was because the cache is bad.
            if not jwt_key_was_cached:
                # It wasn't cached anyway so we an just raise our exception
                self.log_and_raise(_("JWT decoding failed: %(e)s, check your key and generated token"), {"e": de})

            # We had a cached key so lets get the key again ignoring the cache
            new_decryption_key, _junk = self.get_decryption_key(
                jwt_key_setting,
                validate_certs=get_setting("ANSIBLE_BASE_JWT_VALIDATE_CERT", True),
                timeout=get_setting("ANSIBLE_BASE_JWT_URL_TIMEOUT", 30),
                ignore_cache=True,
            )
            if new_decryption_key == decryption_key:
                # The new key matched the old key so don't even try and decrypt again, the key just doesn't match
                self.log_and_raise(_("JWT decoding failed: %(e)s, cached key was correct; check your key and generated token"), {"e": de})
            # Since we got a new key, lets go ahead and try to validate the token again.
            # If it fails this time we can just raise whatever
            validated_body = self.validate_token(token, new_decryption_key)

        # Let's see if we have the same user info in the cache already
        is_cached, user_defaults = self.check_user_in_cache(validated_body)

        user_model = get_user_model()
        user = None
        if is_cached:
            try:
                user = user_model.objects.get(username=validated_body['sub'])
            except user_model.DoesNotExist:
                # ooofff... I'm sorry, you user was in the cache but deleted from the database?
                # but now you have to pay the price to continue logging in
                pass

        if not user:
            # Either the user wasn't cached or the requested user was not in the DB so we need to make a new one
            user, created = user_model.objects.update_or_create(
                username=validated_body["sub"],
                defaults=user_defaults,
            )
            if created:
                logger.warn(f"New user {user.username} created from JWT auth")

        setattr(user, "resource_api_actions", validated_body.get("resource_api_actions", None))

        logger.info(f"User {user.username} authenticated from JWT auth")
        return user, validated_body

    def log_and_raise(self, conditional_translate_object, expand_values={}):
        logger.error(conditional_translate_object.not_translated() % expand_values)
        raise AuthenticationFailed(conditional_translate_object.translated() % expand_values)

    def check_user_in_cache(self, validated_body: dict) -> Tuple[bool, dict]:
        # These are the defaults which will get passed to the user creation and what we expect in the cache
        expected_cache_value = {
            "first_name": validated_body["first_name"],
            "last_name": validated_body["last_name"],
            "email": validated_body["email"],
            "is_superuser": validated_body["is_superuser"],
        }
        cached_user = cache.get(validated_body["sub"], None)
        # If the user was in the cache and the values of the cache match the expected values we had it in cache
        if cached_user is not None and cached_user == expected_cache_value:
            return True, expected_cache_value
        # The user was not previously in the cache, set the user in the cache so it is found on future requests
        cache.set(validated_body["sub"], expected_cache_value, timeout=self.get_cache_timeout())
        return False, expected_cache_value

    def get_key_from_cache(self, ignore_cache: bool = False) -> Optional[str]:
        # If we are not ignoring the cache (forcing a reload of the key), check it
        logger.debug(f"Ignore cache is {ignore_cache}")
        if not ignore_cache:
            key = cache.get(cache_key, None)
            logger.debug(f"Cached key is {key}")
            # We had a key in the cache so we can return that
            if key:
                return key
        return None

    def get_decryption_key_from_url(self, url: str, timeout: int = 30, validate_certs: bool = True, ignore_cache: bool = False) -> Tuple[str, bool]:
        cached_key = self.get_key_from_cache(ignore_cache)
        if cached_key:
            logger.debug(f"Loading decryption key from cache instead of from url {url}")
            return cached_key, True

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
            return response.text, False
        except requests.exceptions.ConnectionError as e:
            self.log_and_raise(_("Failed to connect to %(jwt_key_url)s: %(e)s"), {"jwt_key_url": jwt_key_url, "e": e})
        except requests.exceptions.Timeout:
            self.log_and_raise(_("Timed out after %(timeout)s secs when connecting to %(jwt_key_url)s"), {"timeout": timeout, "jwt_key_url": jwt_key_url})
        except requests.exceptions.RequestException as e:
            self.log_and_raise(_("Failed to get JWT decryption key from JWT server: (%(e_class_name)s) %(e)s"), {"e_class_name": e.__class__.__name__, "e": e})

    def get_decryption_key_from_file(self, file_path: str, ignore_cache: bool = False) -> Tuple[str, bool]:
        cached_key = self.get_key_from_cache(ignore_cache)
        if cached_key:
            logger.debug(f"Loading decryption key from cache instead of from file {file_path}")
            return cached_key, True

        logger.debug(f"Loading decryption key from file {file_path}")

        try:
            with open(file_path, "r") as f:
                cert = f.read()
            return cert, False
        except FileNotFoundError:
            self.log_and_raise(_("The specified file %(file_path)s does not exist"), {"file_path": file_path})
        except IsADirectoryError:
            self.log_and_raise(_("The specified file %(file_path)s is not a file"), {"file_path": file_path})
        except PermissionError:
            self.log_and_raise(_("Permission error when reading %(file_path)s"), {"file_path": file_path})
        except Exception as e:
            self.log_and_raise(_("Failed reading %(file_path)s: %(e)s"), {"file_path": file_path, "e": e})

    def get_decryption_key(self, url_or_string: str, ignore_cache: bool = False, validate_certs: bool = True, timeout: Optional[int] = 30) -> Tuple[str, bool]:
        # We don't check the cache right away here because we only want to check the cache if its a file or URL.
        # A hard coded key would be less efficient if we were attempting to load the cache every time.
        cached = False
        url_info = urlparse(url_or_string)
        key = None
        logger.info(f"Loading decryption key from {url_or_string} scheme {url_info.scheme}")
        if url_info.scheme in ["http", "https"]:
            key, cached = self.get_decryption_key_from_url(url_or_string, timeout, validate_certs, ignore_cache)
        elif url_info.scheme == "file":
            file_path = url_info.path
            key, cached = self.get_decryption_key_from_file(file_path, ignore_cache)
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

        # Here we cache whatever key we were able to load
        cache.set(cache_key, key, timeout=self.get_cache_timeout())
        return key, cached

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
            raise e  # This will be handled higher up
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
