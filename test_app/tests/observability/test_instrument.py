import logging
from unittest.mock import MagicMock, patch

from opentelemetry import trace
from opentelemetry._logs import get_logger_provider
from opentelemetry.sdk._logs import LoggingHandler

from ansible_base.observability.instrument import _attach_handler_to_non_propagating_loggers, _instrument_psycopg


def test_spans_emitted(otel_memory_exporters):
    span_exporter, _ = otel_memory_exporters
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("test-span"):
        pass
    spans = span_exporter.get_finished_spans()
    assert any(s.name == "test-span" for s in spans)


def test_non_propagating_logger_exports_records(otel_memory_exporters):
    _, log_exporter = otel_memory_exporters

    logger = logging.getLogger("test.non_propagating")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)

    handler = LoggingHandler(level=logging.NOTSET, logger_provider=get_logger_provider())
    logger.addHandler(handler)

    try:
        logger.warning("non-propagating test message")
        records = log_exporter.get_finished_logs()
        bodies = [r.log_record.body for r in records]
        assert any("non-propagating test message" in b for b in bodies)
    finally:
        logger.removeHandler(handler)
        logger.propagate = True


def test_opentelemetry_logger_excluded_from_handler_attachment():
    otel_logger = logging.getLogger("opentelemetry.test.excluded")
    otel_logger.propagate = False

    handler_types_before = {type(h) for h in otel_logger.handlers}

    handler = LoggingHandler(level=logging.NOTSET, logger_provider=get_logger_provider())
    _attach_handler_to_non_propagating_loggers(handler)

    handler_types_after = {type(h) for h in otel_logger.handlers}
    assert handler_types_before == handler_types_after, "LoggingHandler must not be attached to opentelemetry.* loggers"


def test_instrument_psycopg_uses_psycopg2():
    mock_instrumentor = MagicMock()
    with patch.dict('sys.modules', {'opentelemetry.instrumentation.psycopg2': MagicMock(Psycopg2Instrumentor=mock_instrumentor)}):
        _instrument_psycopg()
    mock_instrumentor.return_value.instrument.assert_called_once()


def test_instrument_psycopg_falls_back_to_psycopg():
    mock_instrumentor = MagicMock()
    with patch.dict(
        'sys.modules',
        {
            'opentelemetry.instrumentation.psycopg2': None,
            'opentelemetry.instrumentation.psycopg': MagicMock(PsycopgInstrumentor=mock_instrumentor),
        },
    ):
        _instrument_psycopg()
    mock_instrumentor.return_value.instrument.assert_called_once()


def test_instrument_psycopg_warns_when_neither_found(caplog):
    with patch.dict(
        'sys.modules',
        {
            'opentelemetry.instrumentation.psycopg2': None,
            'opentelemetry.instrumentation.psycopg': None,
        },
    ):
        with caplog.at_level(logging.WARNING, logger='ansible_base.observability.instrument'):
            _instrument_psycopg()
    assert any("psycopg2 nor psycopg found" in r.message for r in caplog.records)
