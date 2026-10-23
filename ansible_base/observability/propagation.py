import contextvars
import re

import requests
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from opentelemetry.trace import Span

_active_propagation_headers: contextvars.ContextVar[dict[str, str]] = contextvars.ContextVar('active_propagation_headers', default={})


def headers_to_propagate(meta: dict[str, str]) -> dict[str, str]:
    patterns = getattr(settings, 'ANSIBLE_OBSERVABILITY_CAPTURE_HEADERS', [])
    if not patterns:
        return {}
    combined = re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)
    result = {}
    for key, value in meta.items():
        if key.startswith("HTTP_"):
            header_name = key[5:].replace("_", "-")
            if combined.fullmatch(header_name):
                result[header_name] = value
    return result


def request_hook(_span: Span, request: HttpRequest) -> None:
    headers = headers_to_propagate(request.META)
    request._otel_propagation_token = _active_propagation_headers.set(headers)


def response_hook(_span: Span, request: HttpRequest, _response: HttpResponse) -> None:
    token = getattr(request, '_otel_propagation_token', None)
    if token is not None:
        _active_propagation_headers.reset(token)


def outgoing_request_hook(_span: Span, request: requests.PreparedRequest) -> None:
    for header, value in _active_propagation_headers.get().items():
        request.headers[header] = value
