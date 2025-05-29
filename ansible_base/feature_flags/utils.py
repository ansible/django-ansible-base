from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from flags.sources import get_flags

from ansible_base.lib.dynamic_config.feature_flags.platform_flags import AAP_FEATURE_FLAGS


def get_django_flags():
    return get_flags()


def is_boolean_str(val):
    return val.lower() in {'true', 'false'}


def create_initial_data(**kwargs):
    """
    Loads in platform feature flags when the server starts
    """

    from ansible_base.feature_flags.models.aap_flag import AAPFlag

    def update_feature_flag(existing: AAPFlag, new):
        """
        Update only the required fields of the feature flag model.
        This is used to ensure that flags can be loaded in when the server starts, with any applicable updates.
        """

        existing.support_level = new['support_level']
        existing.visibility = new['visibility']
        existing.ui_name = new['ui_name']
        existing.support_url = new['support_url']
        if 'required' in new:
            existing.required = new['required']
        if 'toggle_type' in new:
            existing.toggle_type = new['toggle_type']
        if 'labels' in new:
            existing.labels = new['labels']
        if 'description' in new:
            existing.description = new['description']
        existing.save()

    def load_feature_flags():
        """
        Loads in all feature flags into the database. Updates them if necessary.
        """
        FeatureFlags = apps.get_model('dab_feature_flags', 'AAPFlag')
        for flag in AAP_FEATURE_FLAGS:
            try:
                existing_flag = FeatureFlags.objects.filter(name=flag['name'], condition=flag['condition'])
                if existing_flag:
                    update_feature_flag(existing_flag.first(), flag)
                else:
                    if hasattr(settings, flag['name']):
                        flag['value'] = getattr(settings, flag['name'])
                    FeatureFlags.objects.create(**flag)
                AAPFlag(**flag).full_clean()
            except ValidationError as e:
                # Ignore this error unless better way to bypass this
                if e.messages[0] == 'Aap flag with this Name, Condition and Value already exists.':
                    pass
                else:
                    # Raise row validation errors
                    raise e

    def delete_feature_flags():
        """
        If a feature flag has been removed from the platform flags list, delete it from the database.
        """
        all_flags = apps.get_model('dab_feature_flags', 'AAPFlag').objects.all()
        for flag in all_flags:
            found = False
            for _flag in AAP_FEATURE_FLAGS:
                if flag.name == _flag['name'] and flag.condition == _flag['condition']:
                    found = True
                    continue
            if found:
                continue
            if not found:
                flag.delete()

    delete_feature_flags()
    load_feature_flags()
