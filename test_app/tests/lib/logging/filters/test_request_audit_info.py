import io
import logging

import pytest
from django.http import HttpRequest

from ansible_base.lib.logging import thread_local
from ansible_base.lib.logging.filters.request_audit_info import RequestAuditInfoFilter


@pytest.fixture
def thread_local_request():
    request = HttpRequest()
    request.method = "GET"
    request.path = "/test"
    request.META = {}
    thread_local.request = request
    yield request
    del thread_local.request


class TestRequestAuditInfoFilterNoRequest:
    def test_filter_returns_true_without_request(self):
        """Filter should always return True even without a request."""
        filter = RequestAuditInfoFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.DEBUG,
            pathname='test.py',
            lineno=1,
            msg='test message',
            args=(),
            exc_info=None,
        )
        assert filter.filter(record) is True

    def test_sets_empty_defaults_without_request(self):
        """Filter should set empty defaults when no request exists."""
        filter = RequestAuditInfoFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.DEBUG,
            pathname='test.py',
            lineno=1,
            msg='test message',
            args=(),
            exc_info=None,
        )
        filter.filter(record)
        assert record.source_ip == ""
        assert record.user_agent == ""


class TestRequestAuditInfoFilterSourceIP:
    @pytest.mark.parametrize(
        "remote_addr,expected_ip",
        [
            ("192.168.1.100", "192.168.1.100"),
            ("10.0.0.1", "10.0.0.1"),
            ("::1", "::1"),
            ("2001:db8::1", "2001:db8::1"),
            ("", ""),
        ],
    )
    def test_extracts_source_ip_from_remote_addr(self, thread_local_request, remote_addr, expected_ip):
        """Filter should extract source IP from REMOTE_ADDR."""
        thread_local_request.META['REMOTE_ADDR'] = remote_addr

        filter = RequestAuditInfoFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.DEBUG,
            pathname='test.py',
            lineno=1,
            msg='test message',
            args=(),
            exc_info=None,
        )
        filter.filter(record)
        assert record.source_ip == expected_ip

    @pytest.mark.parametrize(
        "x_forwarded_for,expected_ip",
        [
            ("192.168.1.100", "192.168.1.100"),
            ("10.0.0.1, 192.168.1.1, 172.16.0.1", "10.0.0.1"),
            ("  203.0.113.50  , 192.168.1.1", "203.0.113.50"),
            ("2001:db8::1, ::1", "2001:db8::1"),
        ],
    )
    def test_extracts_source_ip_from_x_forwarded_for(self, thread_local_request, x_forwarded_for, expected_ip):
        """Filter should prefer X-Forwarded-For header and extract first IP."""
        thread_local_request.META['HTTP_X_FORWARDED_FOR'] = x_forwarded_for
        thread_local_request.META['REMOTE_ADDR'] = "127.0.0.1"  # Should be ignored

        filter = RequestAuditInfoFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.DEBUG,
            pathname='test.py',
            lineno=1,
            msg='test message',
            args=(),
            exc_info=None,
        )
        filter.filter(record)
        assert record.source_ip == expected_ip

    def test_falls_back_to_remote_addr_when_no_x_forwarded_for(self, thread_local_request):
        """Filter should use REMOTE_ADDR when X-Forwarded-For is not present."""
        thread_local_request.META['REMOTE_ADDR'] = "192.168.1.100"
        # No HTTP_X_FORWARDED_FOR

        filter = RequestAuditInfoFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.DEBUG,
            pathname='test.py',
            lineno=1,
            msg='test message',
            args=(),
            exc_info=None,
        )
        filter.filter(record)
        assert record.source_ip == "192.168.1.100"

    def test_empty_ip_when_neither_header_present(self, thread_local_request):
        """Filter should set empty source_ip when no IP headers present."""
        # Clear all META
        thread_local_request.META = {}

        filter = RequestAuditInfoFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.DEBUG,
            pathname='test.py',
            lineno=1,
            msg='test message',
            args=(),
            exc_info=None,
        )
        filter.filter(record)
        assert record.source_ip == ""


class TestRequestAuditInfoFilterUserAgent:
    @pytest.mark.parametrize(
        "user_agent",
        [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "curl/7.68.0",
            "python-requests/2.28.0",
            "Ansible/2.15.0",
            "",
        ],
    )
    def test_extracts_user_agent(self, thread_local_request, user_agent):
        """Filter should extract user agent from HTTP_USER_AGENT."""
        thread_local_request.META['HTTP_USER_AGENT'] = user_agent

        filter = RequestAuditInfoFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.DEBUG,
            pathname='test.py',
            lineno=1,
            msg='test message',
            args=(),
            exc_info=None,
        )
        filter.filter(record)
        assert record.user_agent == user_agent

    def test_empty_user_agent_when_not_present(self, thread_local_request):
        """Filter should set empty user_agent when header not present."""
        thread_local_request.META = {}

        filter = RequestAuditInfoFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.DEBUG,
            pathname='test.py',
            lineno=1,
            msg='test message',
            args=(),
            exc_info=None,
        )
        filter.filter(record)
        assert record.user_agent == ""


class TestRequestAuditInfoFilterCombined:
    def test_extracts_both_ip_and_user_agent(self, thread_local_request):
        """Filter should extract both source IP and user agent."""
        thread_local_request.META['REMOTE_ADDR'] = "192.168.1.100"
        thread_local_request.META['HTTP_USER_AGENT'] = "curl/7.68.0"

        filter = RequestAuditInfoFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.DEBUG,
            pathname='test.py',
            lineno=1,
            msg='test message',
            args=(),
            exc_info=None,
        )
        result = filter.filter(record)

        assert result is True
        assert record.source_ip == "192.168.1.100"
        assert record.user_agent == "curl/7.68.0"

    def test_full_flow_with_x_forwarded_for(self, thread_local_request):
        """Test full extraction with X-Forwarded-For (proxy scenario)."""
        thread_local_request.META['HTTP_X_FORWARDED_FOR'] = "203.0.113.50, 192.168.1.1"
        thread_local_request.META['REMOTE_ADDR'] = "10.0.0.1"
        thread_local_request.META['HTTP_USER_AGENT'] = "Mozilla/5.0 (X11; Linux x86_64)"

        filter = RequestAuditInfoFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.DEBUG,
            pathname='test.py',
            lineno=1,
            msg='test message',
            args=(),
            exc_info=None,
        )
        filter.filter(record)

        assert record.source_ip == "203.0.113.50"
        assert record.user_agent == "Mozilla/5.0 (X11; Linux x86_64)"


class TestRequestAuditInfoFilterIntegration:
    def test_filter_in_logging_chain(self, admin_api_client):
        """Test the filter works in a real logging chain with HTTP request."""
        stream = io.StringIO()
        root_logger = logging.getLogger()
        handler = logging.StreamHandler(stream)
        formatter = logging.Formatter('(test_audit_info) %(asctime)s %(levelname)-8s [%(source_ip)s] "%(user_agent)s" %(name)s %(message)s')
        handler.setFormatter(formatter)

        # Add our filter
        audit_filter = RequestAuditInfoFilter()
        handler.addFilter(audit_filter)
        root_logger.addHandler(handler)

        try:
            admin_api_client.get(
                "/",
                HTTP_X_FORWARDED_FOR="192.168.1.100",
                HTTP_USER_AGENT="test-agent/1.0",
            )

            handler.flush()
            log_output = stream.getvalue()

            # Sanity check - our formatter is being used
            assert "(test_audit_info)" in log_output

            # Check that IP and user agent appear in the log output
            assert "[192.168.1.100]" in log_output
            assert '"test-agent/1.0"' in log_output
        finally:
            handler.close()
            root_logger.removeHandler(handler)
