import logging
from pathlib import Path

import yaml
from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from flags.sources import get_flags

logger = logging.getLogger('ansible_base.feature_flags.utils')


def get_django_flags():
    return get_flags()


def feature_flags_list():
    current_dir = Path(__file__).parent
    flags_list_file = current_dir / 'definitions/feature_flags.yaml'
    with open(flags_list_file, 'r') as file:
        try:
            return yaml.safe_load(file)
        except yaml.YAMLError as exc:
            print(exc)


def create_initial_data(**kwargs):  # NOSONAR
    """
    Loads in platform feature flags when the server starts
    """
    purge_feature_flags()
    load_feature_flags()


def update_feature_flag(existing, new):
    """
    Update only the required fields of the feature flag model.
    This is used to ensure that flags can be loaded in when the server starts, with any applicable updates.
    """
    existing.support_level = new.get('support_level')
    existing.visibility = new.get('visibility')
    existing.ui_name = new.get('ui_name')
    existing.support_url = new.get('support_url')
    existing.required = new.get('required', False)
    existing.toggle_type = new.get('toggle_type', 'run-time')
    existing.labels = new.get('labels', [])
    existing.description = new.get('description', '')
    return existing


def load_feature_flags():
    """
    Loads in all feature flags into the database. Updates them if necessary.
    """
    from ansible_base.resource_registry.models import Resource
    from ansible_base.resource_registry.signals.handlers import no_reverse_sync

    feature_flags_model = apps.get_model('dab_feature_flags', 'AAPFlag')
    for flag in feature_flags_list():
        try:
            existing_flag = feature_flags_model.objects.filter(name=flag['name'], condition=flag['condition'])
            if existing_flag:
                feature_flag = update_feature_flag(existing_flag.first(), flag)
            else:
                if hasattr(settings, flag['name']):
                    flag['value'] = getattr(settings, flag['name'])
                feature_flag = feature_flags_model(**flag)
            try:
                feature_flag.full_clean()
            except Resource.DoesNotExist:
                # Resource may not exist yet during restore scenarios.
                # This is safe to ignore - the resource will be created when the flag is saved.
                logger.info(f"Resource not found for feature flag: {flag['name']} during validation, will be created on save")
            with no_reverse_sync():
                feature_flag.save()
        except ValidationError as e:
            # Ignore this error unless better way to bypass this
            if e.messages[0] == 'Aap flag with this Name and Condition already exists.':
                logger.info(f"Feature flag: {flag['name']} already exists")
            else:
                error_msg = f"Invalid feature flag: {flag['name']}. Error: {e}"
                logger.error(error_msg)


def purge_feature_flags():
    """
    If a feature flag has been removed from the platform flags list, purge it from the database.
    """
    from ansible_base.resource_registry.signals.handlers import no_reverse_sync

    all_flags = apps.get_model('dab_feature_flags', 'AAPFlag').objects.all()
    for flag in all_flags:
        found = False
        for _flag in feature_flags_list():
            if flag.name == _flag['name'] and flag.condition == _flag['condition']:
                found = True
                break
        if found:
            continue
        if not found:
            logger.info(f"Deleting feature flag: {flag.name} as it is no longer available as a platform flag")
            with no_reverse_sync():
                flag.delete()
