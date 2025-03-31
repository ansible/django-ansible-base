import importlib
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.db.utils import IntegrityError
from django.http import HttpResponseNotFound
from social_core.utils import setting_name
from social_django.models import Association, Code, Nonce, Partial
from social_django.storage import BaseDjangoStorage
from social_django.strategy import DjangoStrategy

from ansible_base.authentication.authenticator_plugins.utils import generate_authenticator_slug, get_authenticator_class, get_authenticator_plugins
from ansible_base.authentication.models import Authenticator, AuthenticatorUser
from ansible_base.lib.utils.response import get_fully_qualified_url

logger = logging.getLogger('ansible_base.authentication.social_auth')


SOCIAL_AUTH_PIPELINE_FAILED_STATUS = "pipeline-failed"


class AuthenticatorStorage(BaseDjangoStorage):
    user = AuthenticatorUser
    nonce = Nonce
    association = Association
    code = Code
    partial = Partial

    @classmethod
    def is_integrity_error(cls, exception):
        return exception.__class__ is IntegrityError


class AuthenticatorStrategy(DjangoStrategy):
    def __init__(self, storage, request=None, tpl=None):
        super().__init__(storage, request, tpl)
        self.settings = {}
        fq_function_name = getattr(settings, 'ANSIBLE_BASE_SOCIAL_AUTH_STRATEGY_SETTINGS_FUNCTION', None)
        if fq_function_name:
            logger.debug(f"Attempting to load social settings from {fq_function_name}")
            try:
                module_name, _, function_name = fq_function_name.rpartition('.')
                the_function = getattr(importlib.import_module(module_name), function_name)
                self.settings = the_function()
            except Exception as e:
                logger.error(f"Failed to run {fq_function_name} to get additional settings: {e}")

    # override setting to pass the backend to get_setting
    def setting(self, name, default=None, backend=None):
        names = [setting_name(name), name]
        if backend:
            names.insert(0, setting_name(backend.name, name))
        for name in names:
            try:
                return self.get_setting(name, backend)
            except (AttributeError, KeyError):
                pass
        return default

    # load the authenticator setting from the database object.
    def get_setting(self, name, backend):
        # try to load the value from the db.
        if backend and hasattr(backend, 'database_instance'):
            value = backend.database_instance.configuration.get(name, None)
            if value is not None:
                return value

            # next check the ADDITIONAL_UNVERIFIED_ARGS
            additional_args = backend.database_instance.configuration.get('ADDITIONAL_UNVERIFIED_ARGS', {})
            value = additional_args.get(name, None)
            if value is not None:
                return value

        # See if we have the setting ourselves
        if self.settings.get(name, None):
            return self.settings.get(name)

        # fall back to settings module
        return super().get_setting(name)

    def get_backends(self):
        """Return configured backends"""
        return get_authenticator_plugins()

    def get_backend_class(self, name):
        """Return a configured backend class"""
        # TODO: This can raise an exception if the back end is fubar
        return get_authenticator_class(name)

    def get_backend(self, slug, redirect_uri=None, *args, **kwargs):
        """Add the database instance arg into the social auth backend."""

        db_instance = Authenticator.objects.get(slug=slug)
        Backend = self.get_backend_class(db_instance.type)

        kwargs["database_instance"] = db_instance
        kwargs["redirect_uri"] = redirect_uri
        args = (self,) + args

        return Backend(
            *args,
            **kwargs,
        )

    def session_set(self, name, value):
        # Social auth tries to set auth_user.provider as a value in the session. Since
        # we've set provider to be a foreign key to the Authenticator model, this can
        # receive an Authenticator object, which isn't json serializeable and causes the
        # session to break.
        if isinstance(value, models.Model):
            value = str(value)
        return super().session_set(name, value)

    def create_user(self, *args, **kwargs):
        # In the social pipeline we still want to call social_core.pipeline.user.create_user
        #     because it will pull in the user fields if set.
        # However, we want to be able to connect to existing Users which social auth does not handle well.
        # This is a short circuit to return an already created user to appease social auth login in our model.
        try:
            # Return the existing user if it already exists.
            return get_user_model().objects.get(username=kwargs.get('username', None))
        except get_user_model().DoesNotExist:
            # Call the parent class if the User has not already been created.
            return self.storage.user.create_user(*args, **kwargs)


class AuthenticatorConfigTestStrategy(AuthenticatorStrategy):
    def __init__(self, storage, request=None, tpl=None, additional_settings={}):
        super().__init__(storage, request, tpl)
        self.settings.update(additional_settings)


class SocialAuthMixin:
    configuration_encrypted_fields = []
    logger = None
    groups_claim = "Group"

    def __init__(self, *args, **kwargs):
        # social auth expects the first arg to be a strategy instance. Since this has
        # to be instantiated outside of social auth, make sure that the strategy arg
        # is present.
        args = self.ensure_strategy_in_args(args)
        self.database_instance = kwargs.pop("database_instance", None)
        super().__init__(*args, **kwargs)
        self.set_logger(self.logger)

    def start(self):
        # This will be run on the /login call and we want to return a 404 if the authenticator is not enabled.
        if not self.database_instance.enabled:
            logger.error(f"Authentication attempted with disabled authenticator {self.database_instance.name}")
            return HttpResponseNotFound()
        return super().start()

    @property
    def name(self):
        return str(self.database_instance.slug)

    def get_user_groups(self, extra_groups=None):
        """
        Receives the user object that .authenticate returns.
        """
        return []

    def ensure_strategy_in_args(self, args):
        if len(args) == 0:
            args = (AuthenticatorStrategy(storage=AuthenticatorStorage()),)

        return args


class SocialAuthValidateCallbackMixin:
    def validate(self, serializer, data):
        # if we have an instance already and we didn't get a configuration parameter we are just updating other fields and can return
        if serializer.instance and 'configuration' not in data:
            return data

        configuration = data['configuration']
        if not configuration.get('CALLBACK_URL', None):
            if not serializer.instance:
                data["slug"] = generate_authenticator_slug(data.get("slug"))
                slug = data["slug"]
            else:
                slug = serializer.instance.slug

            configuration['CALLBACK_URL'] = get_fully_qualified_url('social:complete', kwargs={'backend': slug})

        return data


def create_user_claims_pipeline(*args, backend, response, **kwargs):
    from ansible_base.authentication.utils.claims import update_user_claims

    groups_claim = backend.groups_claim if backend.groups_claim is not None else "Group"

    extra_groups = response[groups_claim] if groups_claim in response else []
    logger.debug(f'groups extracted from UserInfo. "{groups_claim}": {extra_groups}')

    # attempt to get group claims from id token if current backend has it
    if hasattr(backend, "id_token"):
        extra_groups_from_id_token = backend.id_token.get(groups_claim, [])
        logger.debug(f'groups extracted from id_token. "{groups_claim}": {extra_groups_from_id_token}')

        # Merge groups from UserInfo and groups_claim in id_token and remove duplicates
        extra_groups = list(set(extra_groups + extra_groups_from_id_token))

    logger.debug(f'updating user claims with groups claim "{groups_claim}": {extra_groups}')

    user = update_user_claims(kwargs["user"], backend.database_instance, backend.get_user_groups(extra_groups))
    if user is None:
        return SOCIAL_AUTH_PIPELINE_FAILED_STATUS
