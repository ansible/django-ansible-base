from django.apps import AppConfig


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
                model.connect_signals()
