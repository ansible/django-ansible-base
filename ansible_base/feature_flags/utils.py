from django.conf import settings


def get_django_flags():
    if hasattr(settings, 'FLAGS'):
        return settings.FLAGS
    return {}
