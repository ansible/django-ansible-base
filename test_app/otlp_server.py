import collections
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import grpc
from opentelemetry.proto.collector.logs.v1 import logs_service_pb2, logs_service_pb2_grpc
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2, trace_service_pb2_grpc

logger = logging.getLogger(__name__)

recent_spans = collections.deque(maxlen=200)
recent_logs = collections.deque(maxlen=200)
_lock = threading.Lock()

PORT = 4317
_server = None  # module-level ref keeps server alive


def _attr_val(v):
    kind = v.WhichOneof("value")
    if kind == "string_value":
        return v.string_value
    if kind == "int_value":
        return v.int_value
    if kind == "double_value":
        return v.double_value
    if kind == "bool_value":
        return v.bool_value
    return str(v)


class TraceServicer(trace_service_pb2_grpc.TraceServiceServicer):
    def Export(self, request, context):
        with _lock:
            for resource_spans in request.resource_spans:
                for scope_spans in resource_spans.scope_spans:
                    for span in scope_spans.spans:
                        recent_spans.append(
                            {
                                "name": span.name,
                                "trace_id": span.trace_id.hex(),
                                "span_id": span.span_id.hex(),
                                "start_ns": span.start_time_unix_nano,
                                "end_ns": span.end_time_unix_nano,
                                "status": span.status.code,
                                "attrs": {kv.key: _attr_val(kv.value) for kv in span.attributes},
                            }
                        )
        return trace_service_pb2.ExportTraceServiceResponse()


class LogsServicer(logs_service_pb2_grpc.LogsServiceServicer):
    def Export(self, request, context):
        with _lock:
            for resource_logs in request.resource_logs:
                for scope_logs in resource_logs.scope_logs:
                    for log in scope_logs.log_records:
                        recent_logs.append(
                            {
                                "body": _attr_val(log.body),
                                "severity": log.severity_text,
                                "timestamp_ns": log.time_unix_nano,
                                "attrs": {kv.key: _attr_val(kv.value) for kv in log.attributes},
                            }
                        )
        return logs_service_pb2.ExportLogsServiceResponse()


def start():
    global _server
    _server = grpc.server(ThreadPoolExecutor(max_workers=4))
    trace_service_pb2_grpc.add_TraceServiceServicer_to_server(TraceServicer(), _server)
    logs_service_pb2_grpc.add_LogsServiceServicer_to_server(LogsServicer(), _server)
    _server.add_insecure_port(f"[::]:{PORT}")
    _server.start()
    logger.info("OTLP gRPC server listening on port %d", PORT)
    _server.wait_for_termination()  # block the daemon thread; keeps server alive
