import logging
from typing import Optional, Tuple

import jwt
from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from ansible_base.jwt_consumer.common.cache import JWTCache
from ansible_base.jwt_consumer.common.cert import JWTCert, JWTCertException
from ansible_base.lib.utils.translations import translatableConditionally as _
from ansible_base.resource_registry.models import Resource

logger = logging.getLogger("ansible_base.jwt_consumer.common.auth")


# These fields are used to both map the user as well as to validate the JWT token
default_mapped_user_fields = [
    "username",
    "first_name",
    "last_name",
    "email",
    "is_superuser",
]


class JWTCommonAuth:
    def __init__(self, user_fields=default_mapped_user_fields) -> None:
        self.mapped_user_fields = user_fields
        self.cache = JWTCache()
        self.user = None
        self.token = None
        if hasattr(settings, 'ANSIBLE_BASE_TEAM_MODEL'):
            self.team_content_type = ContentType.objects.get_for_model(apps.get_model(settings.ANSIBLE_BASE_TEAM_MODEL))
        if hasattr(settings, 'ANSIBLE_BASE_ORGANIZATION_MODEL'):
            self.org_content_type = ContentType.objects.get_for_model(apps.get_model(settings.ANSIBLE_BASE_ORGANIZATION_MODEL))

    def parse_jwt_token(self, request):
        """
        parses the given request setting self.user and self.token
        """

        self.user = None
        self.token = None

        logger.debug("Starting JWT Authentication")
        if request is None:
            return

        token_from_header = request.headers.get("X-DAB-JW-TOKEN", None)
        if not token_from_header:
            logger.info("X-DAB-JW-TOKEN header not set for JWT authentication")
            return
        logger.debug(f"Received JWT auth token: {token_from_header}")

        cert_object = JWTCert()
        try:
            cert_object.get_decryption_key()
        except JWTCertException as jce:
            logger.error(jce)
            raise AuthenticationFailed(jce)

        if cert_object.key is None:
            return None, None

        try:
            self.token = self.validate_token(token_from_header, cert_object.key)
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
            self.token = self.validate_token(token_from_header, cert_object.key)

        # Let's see if we have the same user info in the cache already
        is_cached, user_defaults = self.cache.check_user_in_cache(self.token)

        user_model = get_user_model()
        self.user = None
        if is_cached:
            try:
                self.user = user_model.objects.get(resource__ansible_id=self.token['sub'])
            except user_model.DoesNotExist:
                # ooofff... I'm sorry, you user was in the cache but deleted from the database?
                # but now you have to pay the price to continue logging in
                pass

        if not self.user:
            # Either the user wasn't cached or the requested user was not in the DB so we need to make a new one
            self.user, created = user_model.objects.update_or_create(
                username=self.token["user_data"]['username'],
                defaults=user_defaults,
            )
            if created:
                logger.warn(f"New user {self.user.username} created from JWT auth")

        setattr(self.user, "resource_api_actions", self.token.get("resource_api_actions", None))

        logger.info(f"User {self.user.username} authenticated from JWT auth")

    def log_and_raise(self, conditional_translate_object, expand_values={}):
        logger.error(conditional_translate_object.not_translated() % expand_values)
        raise AuthenticationFailed(conditional_translate_object.translated() % expand_values)

    def map_user_fields(self):
        if self.token is None or self.user is None:
            logger.error("Unable to map user fields because user or token is not defined, please call authenticate first")
            return

        user_needs_save = False
        for attribute in self.mapped_user_fields:
            old_value = getattr(self.user, attribute, None)
            new_value = self.token.get('user_data', {}).get(attribute, None)
            if old_value != new_value:
                logger.debug(f"Changing {attribute} for {self.user.username} from {old_value} to {new_value}")
                setattr(self.user, attribute, new_value)
                user_needs_save = True
        if user_needs_save:
            logger.info(f"Saving user {self.user.username}")
            self.user.save()

    def validate_token(self, unencrypted_token, decryption_key):
        validated_body = None

        local_required_field = ["sub", "user_data", "exp", "objects", "object_roles", "global_roles", "version"]

        # Decrypt the token
        try:
            logger.info("Decrypting token")
            validated_body = jwt.decode(
                unencrypted_token,
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

        # Ensure all of the user pieces are part of the token
        missing_user_data = []
        for field in self.mapped_user_fields:
            if field not in validated_body['user_data']:
                missing_user_data.append(field)
        if missing_user_data:
            self.log_and_raise(_("JWT did not have proper user_data, missing fields: %(missing_fields)s"), {"missing_fields": ", ".join(missing_user_data)})

        # At this time we are not doing anything with regards to the version other than ensuring its there.

        return validated_body

    def get_role_definition(self, name: str) -> Optional[Model]:
        """Simply get the RoleDefinition from the database if it exists and handler corner cases

        If this is the name of a managed role for which we have a corresponding definition in code,
        and that role can not be found in the database, it may be created here
        """
        from ansible_base.rbac.models import RoleDefinition

        try:
            return RoleDefinition.objects.get(name=name)
        except RoleDefinition.DoesNotExist:
            from ansible_base.rbac.permission_registry import permission_registry

            constructor = permission_registry.get_managed_role_constructor_by_name(name)
            if constructor:
                rd, _ = constructor.get_or_create(apps)
                return rd
        return None

    def process_rbac_permissions(self):
        """
        This is a default process_permissions which should be usable if you are using RBAC from DAB
        """
        if self.token is None or self.user is None:
            logger.error("Unable to process rbac permissions because user or token is not defined, please call authenticate first")
            return

        for system_role_name in self.token.get("global_roles", []):
            logger.debug(f"Processing system role {system_role_name} for {self.user.username}")
            rd = self.get_role_definition(system_role_name)
            if rd:
                rd.give_global_permission(self.user)
                logger.info(f"Granted user {self.user.username} global role {system_role_name}")
            else:
                logger.error(f"Unable to grant {self.user.username} system level role {system_role_name} because it does not exist")
                continue

        for object_role_name in self.token.get('object_roles', {}).keys():
            rd = self.get_role_definition(object_role_name)
            if rd is None:
                logger.error(f"Unable to grant {self.user.username} object role {object_role_name} because it does not exist")
                continue

            object_type = self.token['object_roles'][object_role_name]['content_type']
            object_indexes = self.token['object_roles'][object_role_name]['objects']

            for index in object_indexes:
                object_data = self.token['objects'][object_type][index]
                resource, obj = self.get_or_create_resource(object_type, object_data)
                if resource is not None:
                    rd.give_permission(self.user, obj)
                    logger.info(f"Granted user {self.user.username} role {object_role_name} to object {obj.name} with ansible_id {object_data['ansible_id']}")

    def get_or_create_resource(self, content_type: str, data: dict) -> Tuple[Optional[Resource], Optional[Model]]:
        """
        Gets or creates a resource from a content type and its default data

        This can only build or get organizations or teams
        """
        object_ansible_id = data['ansible_id']
        try:
            resource = Resource.objects.get(ansible_id=object_ansible_id)
            logger.debug(f"Resource {object_ansible_id} already exists")
            return resource, resource.content_object
        except Resource.DoesNotExist:
            pass

        # The resource was missing so we need to create its stub
        if content_type == 'team':
            # For a team we first have to make sure the org is there
            org_id = data['org']
            organization_data = self.token['objects'][self.org_content_type.model][org_id]

            # Now that we have the org we can build a team
            resource, org = self.get_or_create_resource(self.org_content_type.model, organization_data)
            team, created = self.team_content_type.model_class().objects.get_or_create(
                name=data['name'], organization=org, defaults={'description': 'Waiting for resource sync'}
            )
            team.save()
            if created:
                logger.warning(f"Created team {data['name']}")
            team.resource.ansible_id = object_ansible_id
            team.resource.save()
            return team.resource, team
        elif content_type == 'organization':
            org, created = self.org_content_type.model_class().objects.get_or_create(name=data['name'], defaults={'description': 'Waiting for resource sync'})
            org.save()
            logger.warning(f"Created organization {data['name']}")
            org.resource.ansible_id = object_ansible_id
            org.resource.save()
            return org.resource, org
        else:
            logger.error(f"build_resource_stub does not know how to build an object of type {type}")
            return None, None


class JWTAuthentication(BaseAuthentication):
    map_fields = default_mapped_user_fields
    use_rbac_permissions = False

    def __init__(self):
        self.common_auth = JWTCommonAuth(self.map_fields)

    def authenticate(self, request):
        self.common_auth.parse_jwt_token(request)

        if self.common_auth.user:
            self.process_user_data()
            self.process_permissions()

            return self.common_auth.user, None
        else:
            return None

    def process_user_data(self):
        self.common_auth.map_user_fields()

    def process_permissions(self):
        if self.use_rbac_permissions:
            self.common_auth.process_rbac_permissions()
        else:
            logger.info("process_permissions was not overridden for JWTAuthentication")
