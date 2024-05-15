import logging

import jwt
from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from ansible_base.jwt_consumer.common.cache import JWTCache
from ansible_base.jwt_consumer.common.cert import JWTCert, JWTCertException
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
        self.cache = JWTCache()

    def parse_jwt_token(self, request):
        logger.debug("Starting JWT Authentication")
        token = request.headers.get("X-DAB-JW-TOKEN", None)
        if not token:
            logger.info("X-DAB-JW-TOKEN header not set for JWT authentication")
            return None, None
        logger.debug(f"Received JWT auth token: {token}")

        cert_object = JWTCert()
        try:
            cert_object.get_decryption_key()
        except JWTCertException as jce:
            logger.error(jce)
            raise AuthenticationFailed(jce)

        if cert_object.key is None:
            return None, None

        try:
            validated_body = self.validate_token(token, cert_object.key)
        except jwt.exceptions.DecodeError as de:
            # This exception means the decryption key failed... maybe it was because the cache is bad.
            if not cert_object.cached:
                # It wasn't cached anyway so we an just raise our exception
                self.log_and_raise(_("JWT decoding failed: %(e)s, check your key and generated token"), {"e": de})

            # We had a cached key so lets get the key again ignoring the cache
            old_key = cert_object.key
            try:
                cert_object.get_decryption_key(ignore_cache=True)
            except JWTCertException as jce:
                self.log_and_raise(_("Failed to get JWT token on the second try: %(e)s"), {"e": jce})
            if old_key == cert_object.key:
                # The new key matched the old key so don't even try and decrypt again, the key just doesn't match
                self.log_and_raise(_("JWT decoding failed: %(e)s, cached key was correct; check your key and generated token"), {"e": de})
            # Since we got a new key, lets go ahead and try to validate the token again.
            # If it fails this time we can just raise whatever
            validated_body = self.validate_token(token, cert_object.key)

        # Let's see if we have the same user info in the cache already
        is_cached, user_defaults = self.cache.check_user_in_cache(validated_body)

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
