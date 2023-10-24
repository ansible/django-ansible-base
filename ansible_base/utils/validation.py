from urllib.parse import urlparse, urlunsplit

from django.core.exceptions import ValidationError as LowLevelValidationError
from django.core.validators import URLValidator
from django.utils.translation import gettext_lazy as _
from rest_framework.serializers import ValidationError

VALID_STRING = _('Must be a valid string')


def validate_url_list(urls: list, schemes: list = ['https'], allow_plain_hostname: bool = False) -> None:
    if type(urls) is not list:
        raise ValidationError("Must be a list of urls")
    errors = []
    for a_url in urls:
        if type(a_url) is not str:
            errors.append(f"{a_url} must be a valid url")
            continue
        try:
            validate_url(a_url, schemes=schemes, allow_plain_hostname=allow_plain_hostname)
        except ValidationError:
            errors.append(a_url)
    if errors:
        raise ValidationError(', '.join(errors))


def validate_url(url: str, schemes: list = ['https'], allow_plain_hostname: bool = False) -> None:
    if type(url) is not str:
        raise ValidationError(VALID_STRING)
    if allow_plain_hostname:
        # The default validator will not allow names like https://junk so, if we are ok with simple hostnames we are going to munge up the URL for the validator
        url_parts = urlparse(url)

        # Determine the user_info part of the URL
        user_info = ''
        if url_parts.username:
            user_info = url_parts.username
        if url_parts.password:
            user_info = f'{user_info}:{url_parts.password}'
        if user_info:
            user_info = f"{user_info}@"

        if url_parts.hostname and '.' not in url_parts.hostname:
            hostname = f'{url_parts.hostname}.localhost'
            port = f':{url_parts.port}' if url_parts.port else ''
            netloc = f"{user_info}{hostname}{port}"
            # Reconstruct and override the URL with a valid hostname
            url = urlunsplit([url_parts.scheme, netloc, url_parts.path, url_parts.query, url_parts.fragment])

    validator = URLValidator(schemes=schemes)
    try:
        validator(url)
    except LowLevelValidationError as e:
        raise ValidationError(e.message)
