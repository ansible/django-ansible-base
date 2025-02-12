from django.db.models import SET_NULL, ForeignKey, JSONField, fields

from ansible_base.authentication.authenticator_plugins.utils import generate_authenticator_slug, get_authenticator_plugin
from ansible_base.lib.abstract_models.common import UniqueNamedCommonModel
from ansible_base.lib.utils.models import prevent_search


def get_next_authenticator_order():
    """
    Returns the next authenticator order, which is equals to max(order) + 1
    """
    largest_order_authenticator = Authenticator.objects.values('order').order_by('-order').first()
    return largest_order_authenticator['order'] + 1 if largest_order_authenticator else 1


class Authenticator(UniqueNamedCommonModel):
    ignore_relations = ['authenticator_users']
    enabled = fields.BooleanField(default=False, help_text="Should this authenticator be enabled.")
    create_objects = fields.BooleanField(default=True, help_text="Allow authenticator to create objects (users, teams, organizations).")
    remove_users = fields.BooleanField(
        default=True, help_text="When a user authenticates from this source should they be removed from any other groups they were previously added to."
    )
    configuration = prevent_search(JSONField(default=dict, help_text="The required configuration for this source.", blank=True))
    type = fields.CharField(
        editable=False,
        max_length=256,
        help_text="The type of authentication service this is.",
    )
    order = fields.IntegerField(
        default=get_next_authenticator_order,
        help_text="The order in which an authenticator will be tried. This only pertains to username/password authenticators.",
    )
    slug = fields.SlugField(
        max_length=1024,
        default=None,
        editable=False,
        unique=True,
        help_text="An immutable identifier for the authenticator; used to generate the sso uri for sso authenticator types",
    )
    category = fields.CharField(max_length=30, default=None, help_text="The base type of this authenticator.")

    auto_migrate_users_to = ForeignKey(
        "Authenticator",
        help_text=(
            "Automatically move users from this authenticator to the target authenticator when a matching user logs in via the target authenticator. "
            "For this to work, the field used for the user ID on both authenticators needs to have the same value. This should only be used when "
            "migrating users between two authentication mechanisms that share the same user database (such as when both IDPs share the same "
            "LDAP user directory)."
        ),
        related_name="auto_migrate_users_from",
        null=True,
        on_delete=SET_NULL,
    )

    def save(self, *args, **kwargs):
        from ansible_base.lib.utils.encryption import ansible_encryption

        # Here we are going to allow an exception to raise because what else can we do at this point?
        authenticator = get_authenticator_plugin(self.type)

        if not self.category:
            self.category = authenticator.category

        for field in getattr(authenticator, 'configuration_encrypted_fields', []):
            if field in self.configuration:
                self.configuration[field] = ansible_encryption.encrypt_string(self.configuration[field])

        if not self.slug:
            self.slug = generate_authenticator_slug()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    @classmethod
    def from_db(cls, db, field_names, values):
        from ansible_base.lib.utils.encryption import ansible_encryption

        instance = super().from_db(db, field_names, values)

        try:
            authenticator = get_authenticator_plugin(instance.type)
            for field in getattr(authenticator, 'configuration_encrypted_fields', []):
                if field in instance.configuration:
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

    @property
    def is_last_enabled(self):
        """
        Is this the -only- "enabled" authenticator?

        If used in a conditional statement, this property provides the combination
        of two conditions:
            A) is this enabled?
            B) is this the only authenticator enabled?

        Use this to gate deletion or disabling of authenticators so that the system
        will always have at least one enabled.

        Given that, if the authenticator is NOT enabled, this will always return false
        and could be misleading if no other authenticators are enabled. If you need to
        check if any authenticator is enabled, you should explicitly check with a
        queryset including a filter and an exists call. Do not rely on this property
        alone when making decisions about what can be deleted or disabled.
        """
        if self.enabled and not self.__class__.objects.filter(enabled=True).exclude(id=self.id).exists():
            return True
        return False
