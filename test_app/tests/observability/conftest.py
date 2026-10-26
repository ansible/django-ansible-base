import pytest
from opentelemetry import trace
from opentelemetry._logs import get_logger_provider, set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@pytest.fixture
def otel_memory_exporters():
    span_exporter = InMemorySpanExporter()
    log_exporter = InMemoryLogRecordExporter()

    # Test settings leave the observability app disabled, so install SDK providers
    # when Django hasn't already configured them.
    tracer_provider = trace.get_tracer_provider()
    if not hasattr(tracer_provider, 'add_span_processor'):
        trace.set_tracer_provider(TracerProvider())
        tracer_provider = trace.get_tracer_provider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))

    logger_provider = get_logger_provider()
    if not hasattr(logger_provider, 'add_log_record_processor'):
        set_logger_provider(LoggerProvider())
        logger_provider = get_logger_provider()
    logger_provider.add_log_record_processor(SimpleLogRecordProcessor(log_exporter))

    yield span_exporter, log_exporter

    span_exporter.clear()
    log_exporter.clear()
