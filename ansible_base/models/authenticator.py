from django.db.models import JSONField, fields
from django.utils.text import slugify

from ansible_base.authenticator_plugins.utils import get_authenticator_plugin

from .common import NamedCommonModel


class Authenticator(NamedCommonModel):
    enabled = fields.BooleanField(default=False, help_text="Should this authenticator be enabled")
    create_objects = fields.BooleanField(default=True, help_text="Allow authenticator to create objects in Gateway (users, teams, organizations)")
    # TODO: Implement unique users, remove user, etc with team and org mapping feature.
    users_unique = fields.BooleanField(default=False, help_text="Are users from this source the same as users from another source with the same id")
    remove_users = fields.BooleanField(
        default=True, help_text="When a user authenticates from this source should they be removed from any other groups they were previously added to"
    )
    configuration = JSONField(default=dict, help_text="The required configuration for this source")
    type = fields.CharField(
        max_length=256,
        help_text="The type of authentication service this is",
    )
    order = fields.IntegerField(
        default=1, help_text="The order in which an authenticator will be tried. This only pertains to username/password authenticators"
    )
    slug = fields.SlugField(max_length=1024, default=None, editable=False, unique=True, help_text="An immutable identifier for the authenticator")
    category = fields.CharField(max_length=30, default=None, help_text="The base type of this authenticator")

    reverse_foreign_key_fields = ['authenticator-map']

    def save(self, *args, **kwargs):
        from ansible_base.utils.encryption import ansible_encryption

        authenticator = get_authenticator_plugin(self.type)

        if not self.category:
            self.category = authenticator.category

        for field in getattr(authenticator, 'configuration_encrypted_fields', []):
            if field in self.configuration:
                self.configuration[field] = ansible_encryption.encrypt_string(self.configuration[field])

        if not self.slug:
            self.slug = slugify(f"{self.type}-{self.name}")
            # TODO: What happens if computed slug is not unique?
            # You would have to create an adapter with a name, rename it and then create a new one with the same name
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    @classmethod
    def from_db(cls, db, field_names, values):
        from ansible_base.utils.encryption import ENCRYPTED_STRING, ansible_encryption

        instance = super().from_db(db, field_names, values)

        authenticator = get_authenticator_plugin(instance.type)
        for field in getattr(authenticator, 'configuration_encrypted_fields', []):
            if field in instance.configuration and instance.configuration[field].startswith(ENCRYPTED_STRING):
                instance.configuration[field] = ansible_encryption.decrypt_string(instance.configuration[field])

        return instance
