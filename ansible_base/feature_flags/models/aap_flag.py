from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from ansible_base.lib.abstract_models.common import NamedCommonModel
from ansible_base.resource_registry.fields import AnsibleResourceField


def validate_feature_flag_name(value: str):
    if not value.startswith('FEATURE_') or not value.endswith('_ENABLED'):
        raise ValidationError(_("Feature flag names must follow the format of `FEATURE_<flag-name>_ENABLED`"))


def validate_labels(value):
    """Validate that labels is a list of strings."""
    if value is None:
        return  # Allow null values

    if not isinstance(value, list):
        raise ValidationError(_("Labels must be a list."))

    for item in value:
        if not isinstance(item, str):
            raise ValidationError(_("All labels must be strings."))


class AAPFlag(NamedCommonModel):
    class Meta:
        app_label = "dab_feature_flags"
        unique_together = ("name", "condition")

    def __str__(self):
        return "{name} condition {condition} is set to " "{value}{required}".format(
            name=self.name,
            condition=self.condition,
            value=self.value,
            required=" (required)" if self.required else "",
        )

    resource = AnsibleResourceField(primary_key_field="id")

    name = models.CharField(
        max_length=64,
        null=False,
        help_text=_("The name of the feature flag. Must follow the format of FEATURE_<flag-name>_ENABLED."),
        validators=[validate_feature_flag_name],
        blank=False,
    )
    ui_name = models.CharField(max_length=64, null=False, blank=False, help_text=_("The pretty name to display in the application User Interface"))
    condition = models.CharField(max_length=64, default="boolean", help_text=_("Used to specify a condition, which if met, will enable the feature flag."))
    value = models.CharField(
        max_length=127,
        default="False",
        help_text=_("The value used to evaluate the conditional specified."),
    )
    required = models.BooleanField(
        default=False,
        help_text=_("If multiple conditions are required to be met to enable a feature flag, 'required' can be used to specify the necessary conditionals."),
    )
    support_level = models.CharField(
        max_length=25,
        null=False,
        help_text=_("The support criteria for the feature flag. Must be one of (DEVELOPER_PREVIEW or TECHNOLOGY_PREVIEW)."),
        choices=(
            ("DEVELOPER_PREVIEW", "Developer Preview"),
            ("TECHNOLOGY_PREVIEW", "Technology Preview"),
        ),
        blank=False,
        editable=False,
    )
    visibility = models.BooleanField(
        default=False,
        help_text=_("Controls whether the feature is visible in the UI."),
    )
    toggle_type = models.CharField(
        max_length=20,
        null=False,
        choices=[('install-time', 'install-time'), ('run-time', 'run-time')],
        default='run-time',
        help_text=_("Details whether a flag is toggle-able at run-time or install-time. (Default: 'run-time')."),
    )
    description = models.CharField(max_length=500, null=False, default="", help_text=_("A detailed description giving an overview of the feature flag."))
    support_url = models.CharField(max_length=250, null=False, default="", blank=True, help_text="A link to the documentation support URL for the feature")
    labels = models.JSONField(null=True, default=list, help_text=_("A list of labels for the feature flag."), blank=True, validators=[validate_labels])
