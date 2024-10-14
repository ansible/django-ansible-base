from django import template

from ansible_base.lib.utils import requests as dab_requests

register = template.Library()


@register.simple_tag
def is_proxied_request():
    return dab_requests.is_proxied_request()
