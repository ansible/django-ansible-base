import logging
import os
from typing import Optional

from django.conf import settings
from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.django import DjangoInstrumentor
from opentelemetry.instrumentation.grpc import GrpcInstrumentorServer
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, LogRecordExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

from ansible_base.observability.propagation import outgoing_request_hook, request_hook, response_hook


def _setup_tracing(service_name: Optional[str] = None, span_exporter: Optional[SpanExporter] = None) -> Resource:
    resource = Resource(attributes={SERVICE_NAME: service_name or "aap-generic"})
    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)

    exporter = span_exporter or OTLPSpanExporter()
    schedule_delay = getattr(settings, 'ANSIBLE_OBSERVABILITY_BATCH_DELAY_MS', 5000)
    provider.add_span_processor(BatchSpanProcessor(exporter, schedule_delay_millis=schedule_delay))

    return resource


def _attach_handler_to_non_propagating_loggers(handler: LoggingHandler) -> None:
    for name, logger in logging.Logger.manager.loggerDict.items():
        if isinstance(logger, logging.Logger) and not logger.propagate:
            if not (name == 'opentelemetry' or name.startswith('opentelemetry.')):
                logger.addHandler(handler)


def _setup_logging(resource: Resource, instrument_non_propagating: bool = True, log_exporter: Optional[LogRecordExporter] = None) -> None:
    logger_provider = LoggerProvider(resource=resource)
    set_logger_provider(logger_provider)

    exporter = log_exporter or OTLPLogExporter()

    schedule_delay = getattr(settings, 'ANSIBLE_OBSERVABILITY_BATCH_DELAY_MS', 5000)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter, schedule_delay_millis=schedule_delay))

    # Integrate with Python's standard logging
    handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)
    logging.getLogger().addHandler(handler)

    if instrument_non_propagating:
        # Django apps often configure named loggers with propagate=False for
        # intentional routing (e.g. awx.main.tasks, awx.main.scheduler).
        # Those records never reach the root logger and therefore miss the
        # LoggingHandler above. Attach the handler directly to each such
        # logger so their records still flow into the OTEL log pipeline.
        _attach_handler_to_non_propagating_loggers(handler)


def _instrument_psycopg() -> None:
    try:
        from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor

        Psycopg2Instrumentor().instrument()
    except ModuleNotFoundError:
        try:
            from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor

            PsycopgInstrumentor().instrument()
        except ModuleNotFoundError:
            logging.getLogger(__name__).warning("psycopg2 nor psycopg found. Failed to instrument psycopg.")


def setup_observability(
    service_name: Optional[str] = None,
    instrument_non_propagating: bool = True,
    span_exporter: Optional[SpanExporter] = None,
    log_exporter: Optional[LogRecordExporter] = None,
) -> None:
    """Configure OpenTelemetry tracing and logging for a Django application.

    Instruments Django, psycopg/psycopg2, requests, gRPC, and Python logging.
    Intended to be called once at application startup (e.g. AppConfig.ready()).

    This function is intentionally NOT idempotent. Both set_tracer_provider() and
    set_logger_provider() use a write-once lock internally — a second call silently
    discards the new provider, meaning any parameters passed (span_exporter,
    service_name, log_exporter) would be silently ignored. Additionally,
    _setup_logging() attaches handlers to the root logger; calling it twice would
    duplicate every exported log record. Making this "safe" to call multiple times
    would be misleading: callers would believe their parameters took effect when
    they did not.
    """
    if otlp_endpoint := getattr(settings, 'ANSIBLE_OBSERVABILITY_OTLP_ENDPOINT', None):
        os.environ['OTEL_EXPORTER_OTLP_ENDPOINT'] = otlp_endpoint

    service_name = service_name or getattr(settings, 'ANSIBLE_OBSERVABILITY_SERVICE_NAME', None) or "aap-generic"

    capture_headers = getattr(settings, 'ANSIBLE_OBSERVABILITY_CAPTURE_HEADERS', [])
    if capture_headers:
        joined = ','.join(capture_headers)
        os.environ['OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_REQUEST'] = joined
        os.environ['OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_CLIENT_REQUEST'] = joined

    resource = _setup_tracing(service_name, span_exporter=span_exporter)
    _setup_logging(resource, instrument_non_propagating=instrument_non_propagating, log_exporter=log_exporter)

    DjangoInstrumentor().instrument(request_hook=request_hook, response_hook=response_hook)
    _instrument_psycopg()
    RequestsInstrumentor().instrument(request_hook=outgoing_request_hook)
    GrpcInstrumentorServer().instrument()
    LoggingInstrumentor().instrument()
