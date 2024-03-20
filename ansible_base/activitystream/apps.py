from functools import partial

from django.apps import AppConfig
from django.db.models.signals import m2m_changed, post_save, pre_delete, pre_save

from ansible_base.activitystream.signals import activitystream_create, activitystream_delete, activitystream_m2m_changed, activitystream_update


def connect_activitystream_signals(cls):
    post_save.connect(activitystream_create, sender=cls, dispatch_uid=f'dab_activitystream_{cls.__name__}_create')
    pre_save.connect(activitystream_update, sender=cls, dispatch_uid=f'dab_activitystream_{cls.__name__}_update')
    pre_delete.connect(activitystream_delete, sender=cls, dispatch_uid=f'dab_activitystream_{cls.__name__}_delete')

    # Connect to m2m_changed signal for all m2m fields
    for field in cls._meta.many_to_many:
        if field.name in cls.activity_stream_excluded_field_names:
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
        # Iterate models and look for ones that inherit from AuditableModel.
        # If found, connect the signal to the model by calling its static connect_signals().
        from django.apps import apps

        from ansible_base.activitystream.models import AuditableModel

        for model in apps.get_models():
            if issubclass(model, AuditableModel):
                connect_activitystream_signals(model)
