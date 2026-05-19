import pytest
from opentelemetry import trace
from opentelemetry._logs import get_logger_provider
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@pytest.fixture
def otel_memory_exporters():
    span_exporter = InMemorySpanExporter()
    log_exporter = InMemoryLogRecordExporter()

    # Attach to already-running providers (set by apps.py ready())
    tracer_provider = trace.get_tracer_provider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    get_logger_provider().add_log_record_processor(SimpleLogRecordProcessor(log_exporter))

    yield span_exporter, log_exporter

    span_exporter.clear()
    log_exporter.clear()
