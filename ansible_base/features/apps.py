from django.apps import AppConfig


class FeaturesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ansible_base.features'
    label = 'dab_features'
    verbose_name = 'Features'

    def ready(self):
        import importlib
        import logging

        from django.conf import settings

        from ansible_base.features.models import Feature

        logger = logging.getLogger('ansible_base.features')

        for installed_app in settings.INSTALLED_APPS:
            try:
                module_features = importlib.import_module(f'{installed_app}.dab_features')
                feature_counter = 0
                for feature in module_features.FEATURES:
                    try:
                        feature_model, created = Feature.objects.get_or_create(
                            name=feature['name'],
                            defaults={
                                "short_name": feature['short_name'],
                                "description": feature['description'],
                                "status": feature['status'],
                                "requires_restart": feature['requires_restart'],
                            },
                        )
                        if created:
                            logger.info(f"Add new feature {feature['name']}")
                        else:
                            if feature_model.enabled:
                                logger.warning(f"Running {installed_app} with feature {feature['name']}")
                    except KeyError as ke:
                        logger.error(f"Feature {feature_counter} in {installed_app} is invalid missing {ke}!")
                    feature_counter = feature_counter + 1
            except ModuleNotFoundError:
                pass
