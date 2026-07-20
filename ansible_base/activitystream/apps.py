import logging
import warnings
from functools import partial

from django.apps import AppConfig
from django.db.models.signals import m2m_changed, post_save, pre_delete, pre_save

from ansible_base.activitystream.signals import activitystream_create, activitystream_delete, activitystream_m2m_changed, activitystream_update

logger = logging.getLogger('ansible_base.activitystream')

# Registry of models tracked by the activity stream, populated in ready().
_registered_models = set()


def get_activity_stream_entries(instance):
    """Return activity stream entries for a model instance."""
    from django.contrib.contenttypes.models import ContentType

    from ansible_base.activitystream.models import Entry

    return Entry.objects.filter(content_type=ContentType.objects.get_for_model(instance), object_id=instance.pk).order_by('created')


def get_activity_stream_related_url(instance):
    """Return the activity stream related URL dict for a model instance, or empty dict if not registered."""
    if type(instance) not in _registered_models:
        return {}

    from django.contrib.contenttypes.models import ContentType
    from django.utils.http import urlencode

    from ansible_base.lib.utils.response import get_relative_url

    content_type = ContentType.objects.get_for_model(instance)
    query_kwargs = {
        'content_type': content_type.pk,
        'object_id': instance.pk,
    }
    activity_stream_url = get_relative_url('activitystream-list') + '?' + urlencode(query_kwargs)
    return {
        'activity_stream': activity_stream_url,
    }


def connect_activitystream_signals(cls):
    post_save.connect(activitystream_create, sender=cls, dispatch_uid=f'dab_activitystream_{cls.__name__}_create')
    pre_save.connect(activitystream_update, sender=cls, dispatch_uid=f'dab_activitystream_{cls.__name__}_update')
    pre_delete.connect(activitystream_delete, sender=cls, dispatch_uid=f'dab_activitystream_{cls.__name__}_delete')

    # Connect to m2m_changed signal for all m2m fields
    for field in cls._meta.many_to_many:
        if field.name in getattr(cls, 'activity_stream_excluded_field_names', []):
            continue

        fn = partial(activitystream_m2m_changed, field_name=field.name)
        m2m_changed.connect(
            fn,
            sender=getattr(cls, field.name).through,
            dispatch_uid=f'dab_activitystream_{cls.__name__}_{field.name}_m2m_changed',
            weak=False,
        )


class ActivitystreamConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ansible_base.activitystream'
    label = 'dab_activitystream'
    verbose_name = 'Activity Stream'

    def ready(self):
        from django.apps import apps
        from django.conf import settings

        from ansible_base.activitystream.models import AuditableModel

        # Register models from the ACTIVITY_STREAM_MODELS setting (preferred)
        for app_label, model_name in getattr(settings, 'ACTIVITY_STREAM_MODELS', []):
            try:
                model = apps.get_model(app_label, model_name)
            except LookupError:
                logger.warning(f"ACTIVITY_STREAM_MODELS references '{app_label}.{model_name}', but this model was not found.")
                continue

            connect_activitystream_signals(model)
            _registered_models.add(model)

        # Backward compatibility: also detect AuditableModel subclasses not
        # already covered by the setting and register them with loud warnings.
        for model in apps.get_models():
            if model in _registered_models:
                continue
            if issubclass(model, AuditableModel):
                msg = (
                    f"DEPRECATED: Model '{model._meta.label}' inherits from AuditableModel. "
                    f"Remove AuditableModel from the base classes and add "
                    f"('{model._meta.app_label}', '{model.__name__}') to the "
                    f"ACTIVITY_STREAM_MODELS setting instead. "
                    f"AuditableModel inheritance will stop being detected in a future release."
                )
                warnings.warn(msg, DeprecationWarning, stacklevel=1)
                logger.warning(msg)
                connect_activitystream_signals(model)
                _registered_models.add(model)
