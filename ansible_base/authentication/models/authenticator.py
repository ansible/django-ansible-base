from django.db.models import JSONField, fields
from django.db.models.signals import pre_save
from django.dispatch import receiver

from ansible_base.authentication.authenticator_plugins.utils import generate_authenticator_slug, get_authenticator_plugin
from ansible_base.lib.abstract_models.common import UniqueNamedCommonModel
from ansible_base.lib.utils.models import prevent_search


class Authenticator(UniqueNamedCommonModel):
    ignore_relations = ['authenticator_users']
    enabled = fields.BooleanField(default=False, help_text="Should this authenticator be enabled")
    create_objects = fields.BooleanField(default=True, help_text="Allow authenticator to create objects (users, teams, organizations)")
    remove_users = fields.BooleanField(
        default=True, help_text="When a user authenticates from this source should they be removed from any other groups they were previously added to"
    )
    configuration = prevent_search(JSONField(default=dict, help_text="The required configuration for this source", blank=True))
    type = fields.CharField(
        editable=False,
        max_length=256,
        help_text="The type of authentication service this is",
    )
    order = fields.IntegerField(
        default=0, help_text="The order in which an authenticator will be tried. This only pertains to username/password authenticators"
    )
    slug = fields.SlugField(max_length=1024, default=None, editable=False, unique=True, help_text="An immutable identifier for the authenticator")
    category = fields.CharField(max_length=30, default=None, help_text="The base type of this authenticator")

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
            self.slug = generate_authenticator_slug(self.type, self.name)
            # TODO: What happens if computed slug is not unique?
            # You would have to create an adapter with a name, rename it and then create a new one with the same name
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


@receiver(pre_save, sender=Authenticator)
def set_authenticator_order(sender, instance, **kwargs):
    """
    Signal handler to set the 'order' field for new authenticator instances.
    - If the authenticator is being created without a specified order (defaulting to 0),
      this function sets 'order' to the maximum current value plus one.
    - If the authenticator is created with a specified order, the function uses the given order value.
    - For existing instances being updated, 'order' will be updated with the new value given in the request.

    """
    if instance._state.adding and instance.order == 0:
        largest_order_authenticator = Authenticator.objects.all().order_by('-order').first()
        if largest_order_authenticator:
            instance.order = largest_order_authenticator.order + 1
        else:
            # If no authenticator exists, start with order 1
            instance.order = 1
