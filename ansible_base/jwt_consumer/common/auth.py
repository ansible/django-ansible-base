import logging
from typing import Optional, Tuple

import jwt
from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Model
from django.db.utils import IntegrityError
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from ansible_base.jwt_consumer.common.cache import JWTCache
from ansible_base.jwt_consumer.common.cert import JWTCert, JWTCertException
from ansible_base.lib.logging.runtime import log_excess_runtime
from ansible_base.lib.utils.auth import get_user_by_ansible_id
from ansible_base.lib.utils.translations import translatableConditionally as _
from ansible_base.resource_registry.models import Resource, ResourceType
from ansible_base.resource_registry.signals.handlers import no_reverse_sync

logger = logging.getLogger("ansible_base.jwt_consumer.common.auth")


# These fields are used to both map the user as well as to validate the JWT token
default_mapped_user_fields = [
    "username",
    "first_name",
    "last_name",
    "email",
    "is_superuser",
]

_permission_registry = None


def permission_registry():
    global _permission_registry

    if not _permission_registry:
        from ansible_base.rbac.permission_registry import permission_registry as permission_registry_singleton

        _permission_registry = permission_registry_singleton
    return _permission_registry


class JWTCommonAuth:
    def __init__(self, user_fields=default_mapped_user_fields) -> None:
        self.mapped_user_fields = user_fields
        self.cache = JWTCache()
        self.user = None
        self.token = None

    @log_excess_runtime(logger, debug_cutoff=0.01)
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
            logger.debug("X-DAB-JW-TOKEN header not set for JWT authentication")
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

        self.user = None
        if is_cached:
            try:
                self.user = get_user_by_ansible_id(self.token['sub'])
            except ObjectDoesNotExist:
                # ooofff... I'm sorry, you user was in the cache but deleted from the database?
                # but now you have to pay the price to continue logging in
                pass

        if not self.user:
            # Either the user wasn't cached or the requested user was not in the DB so we need to make a new one
            resource_kwargs = {}
            for resource_key, token_key in (('resource_data', 'user_data'), ('ansible_id', 'sub'), ('service_id', 'service_id')):
                if token_key not in self.token:
                    logger.warning(f'Missing {token_key} in JWT data, omitting {resource_key} from local resource entry')
                else:
                    resource_kwargs[resource_key] = self.token[token_key]
            try:
                resource = Resource.create_resource(ResourceType.objects.get(name="shared.user"), **resource_kwargs)
                self.user = resource.content_object
                logger.info(f"New user {self.user.username} created from JWT auth")
            except IntegrityError as exc:
                logger.debug(f'Existing user {self.token["user_data"]} is a conflict with local user, error: {exc}')
                with no_reverse_sync():
                    if user_defaults['is_superuser'] is False:
                        user_defaults.pop('is_superuser')
                    self.user, created = get_user_model().objects.update_or_create(
                        username=self.token["user_data"]['username'],
                        defaults=user_defaults,
                    )

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
                if attribute == 'is_superuser' and new_value is False:
                    continue
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

            constructor = permission_registry().get_managed_role_constructor_by_name(name)
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

        from ansible_base.rbac.models import RoleUserAssignment

        role_diff = RoleUserAssignment.objects.filter(user=self.user, role_definition__name__in=settings.ANSIBLE_BASE_JWT_MANAGED_ROLES)

        for system_role_name in self.token.get("global_roles", []):
            logger.debug(f"Processing system role {system_role_name} for {self.user.username}")
            rd = self.get_role_definition(system_role_name)
            if rd:
                if rd.name in settings.ANSIBLE_BASE_JWT_MANAGED_ROLES:
                    assignment = rd.give_global_permission(self.user)
                    role_diff = role_diff.exclude(pk=assignment.pk)
                    logger.info(f"Granted user {self.user.username} global role {system_role_name}")
                else:
                    logger.error(f"Unable to grant {self.user.username} system level role {system_role_name} because it is not a JWT managed role")
            else:
                logger.error(f"Unable to grant {self.user.username} system level role {system_role_name} because it does not exist")
                continue

        for object_role_name in self.token.get('object_roles', {}).keys():
            rd = self.get_role_definition(object_role_name)
            if rd is None:
                logger.error(f"Unable to grant {self.user.username} object role {object_role_name} because it does not exist")
                continue
            elif rd.name not in settings.ANSIBLE_BASE_JWT_MANAGED_ROLES:
                logger.error(f"Unable to grant {self.user.username} object role {object_role_name} because it is not a JWT managed role")
                continue

            object_type = self.token['object_roles'][object_role_name]['content_type']
            object_indexes = self.token['object_roles'][object_role_name]['objects']

            for index in object_indexes:
                object_data = self.token['objects'][object_type][index]
                resource, obj = self.get_or_create_resource(object_type, object_data)
                if resource is not None:
                    assignment = rd.give_permission(self.user, obj)
                    role_diff = role_diff.exclude(pk=assignment.pk)
                    logger.info(f"Granted user {self.user.username} role {object_role_name} to object {obj.name} with ansible_id {object_data['ansible_id']}")

        # Remove all permissions not authorized by the JWT
        for role_assignment in role_diff:
            rd = role_assignment.role_definition
            content_object = role_assignment.content_object
            if content_object:
                rd.remove_permission(self.user, content_object)
            else:
                rd.remove_global_permission(self.user)

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
            organization_data = self.token['objects']["organization"][org_id]

            # Now that we have the org we can build a team
            org_resource, _ = self.get_or_create_resource("organization", organization_data)

            resource = Resource.create_resource(
                ResourceType.objects.get(name="shared.team"),
                {"name": data["name"], "organization": org_resource.ansible_id},
                ansible_id=data["ansible_id"],
            )

            return resource, resource.content_object

        elif content_type == 'organization':
            resource = Resource.create_resource(
                ResourceType.objects.get(name="shared.organization"),
                {"name": data["name"]},
                ansible_id=data["ansible_id"],
            )

            return resource, resource.content_object
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
