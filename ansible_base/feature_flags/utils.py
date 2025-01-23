from django.conf import settings


def get_django_flags():
    return getattr(settings, 'FLAGS', {})
