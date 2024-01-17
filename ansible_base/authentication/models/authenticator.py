from django.conf import settings
from django.db.models import JSONField, ManyToManyField, fields

from ansible_base.authentication.authenticator_plugins.utils import generate_authenticator_slug, get_authenticator_plugin
from ansible_base.common.models.common import UniqueNamedCommonModel
from ansible_base.common.utils.models import prevent_search


class Authenticator(UniqueNamedCommonModel):
    enabled = fields.BooleanField(default=False, help_text="Should this authenticator be enabled")
    create_objects = fields.BooleanField(default=True, help_text="Allow authenticator to create objects (users, teams, organizations)")
    # TODO: Implement unique users, remove user, etc with team and org mapping feature.
    users_unique = fields.BooleanField(default=False, help_text="Are users from this source the same as users from another source with the same id")
    remove_users = fields.BooleanField(
        default=True, help_text="When a user authenticates from this source should they be removed from any other groups they were previously added to"
    )
    configuration = prevent_search(JSONField(default=dict, help_text="The required configuration for this source"))
    type = fields.CharField(
        editable=False,
        max_length=256,
        help_text="The type of authentication service this is",
    )
    order = fields.IntegerField(
        default=1, help_text="The order in which an authenticator will be tried. This only pertains to username/password authenticators"
    )
    slug = fields.SlugField(max_length=1024, default=None, editable=False, unique=True, help_text="An immutable identifier for the authenticator")
    category = fields.CharField(max_length=30, default=None, help_text="The base type of this authenticator")
    users = ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='users',
        blank=False,
        help_text="The list of users who have authenticated from this authenticator",
    )

    reverse_foreign_key_fields = ['authenticator-map']

    def save(self, *args, **kwargs):
        from ansible_base.common.utils.encryption import ansible_encryption

        # Here we are going to allow an exception to raise because what else can we do at this point?
        authenticator = get_authenticator_plugin(self.type)

        if not self.category:
            self.category = authenticator.category

        for field in getattr(authenticator, 'configuration_encrypted_fields', []):
            if field in self.configuration:
                self.configuration[field] = ansible_encryption.encrypt_string(self.configuration[field])

        if not self.slug:
            self.slug = generate_authenticator_slug(self.type, self.name)
            # TODO: What happens if computed slug is not unique?
            # You would have to create an adapter with a name, rename it and then create a new one with the same name
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    @classmethod
    def from_db(cls, db, field_names, values):
        from ansible_base.common.utils.encryption import ENCRYPTED_STRING, ansible_encryption

        instance = super().from_db(db, field_names, values)

        try:
            authenticator = get_authenticator_plugin(instance.type)
            for field in getattr(authenticator, 'configuration_encrypted_fields', []):
                if field in instance.configuration and instance.configuration[field].startswith(ENCRYPTED_STRING):
                    instance.configuration[field] = ansible_encryption.decrypt_string(instance.configuration[field])
        except ImportError:
            # A log message will already be displayed if this fails
            pass

        return instance

    def get_login_url(self):
        plugin = get_authenticator_plugin(self.type)
        return plugin.get_login_url(self)

    def related_fields(self, request):
        response = super().related_fields(request)

        try:
            plugin = get_authenticator_plugin(self.type)
            response.update(plugin.add_related_fields(request, self))
        except ImportError:
            # If the plugin was removed we could get an ImportError but we still want to return what we can.
            pass

        return response
