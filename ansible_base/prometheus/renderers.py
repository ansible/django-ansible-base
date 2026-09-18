"""
DRF renderers for the Prometheus metrics endpoint.

PrometheusTextRenderer  — passes raw prometheus_client text bytes through unchanged.
PrometheusJSONRenderer  — converts Prometheus text format to a structured JSON document,
                          matching the format exposed by AWX's PrometheusJSONRenderer.
"""
import json

from prometheus_client import CONTENT_TYPE_LATEST
from prometheus_client.parser import text_string_to_metric_families
from rest_framework.renderers import BaseRenderer


class PrometheusTextRenderer(BaseRenderer):
    """Return Prometheus text exposition format (the default for scrapers)."""

    media_type = 'text/plain'
    format = 'txt'
    charset = 'utf-8'

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if renderer_context:
            response = renderer_context.get('response')
            if response is not None:
                response['Content-Type'] = CONTENT_TYPE_LATEST
        if isinstance(data, bytes):
            return data
        return str(data).encode(self.charset)


class PrometheusJSONRenderer(BaseRenderer):
    """Return Prometheus metrics as a structured JSON document.

    Each key is a metric family name. The value contains the HELP string,
    TYPE, and a list of samples (labels, value, timestamp).

    Example::

        {
          "django_http_requests_total": {
            "help": "Total HTTP requests received",
            "type": "counter",
            "samples": [
              {"labels": {"method": "GET", "view": "...", "status_code": "200"},
               "value": 42.0, "timestamp": null}
            ]
          }
        }
    """

    media_type = 'application/json'
    format = 'json'
    charset = 'utf-8'

    def render(self, data, accepted_media_type=None, renderer_context=None):
        text = data.decode(self.charset) if isinstance(data, bytes) else str(data)
        output = {}
        for family in text_string_to_metric_families(text):
            output[family.name] = {
                'help': family.documentation,
                'type': family.type,
                'samples': [
                    {
                        'labels': sample.labels,
                        'value': sample.value,
                        'timestamp': sample.timestamp,
                    }
                    for sample in family.samples
                ],
            }
        return json.dumps(output).encode(self.charset)
