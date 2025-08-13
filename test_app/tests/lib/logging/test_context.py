import random
import threading
import time
import unittest
import uuid

import pytest

from ansible_base.lib.logging.context import origin_var, trace_context, trace_id_var


class TestTraceContextThreadSafety(unittest.TestCase):
    """
    Tests the thread safety of context variables.
    """

    def test_trace_id_is_thread_safe(self):
        """
        Verify that the trace_id context variable is thread-safe and does not leak between threads.
        """
        results = []

        def target_function(thread_id):
            # Set a unique trace ID for this thread
            trace_id_var.set(f"trace-id-{thread_id}")
            # Sleep for a random, short duration to encourage thread interleaving
            time.sleep(random.uniform(0.01, 0.05))
            # Get the trace ID and verify it has not been changed by another thread
            retrieved_id = trace_id_var.get()
            # Store the result of the check for the main thread to verify
            results.append(retrieved_id == f"trace-id-{thread_id}")

        threads = []
        for i in range(10):
            thread = threading.Thread(target=target_function, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Verify that all threads successfully retrieved their own context
        self.assertEqual(len(results), 10, "Not all threads completed successfully.")
        self.assertTrue(all(results), "Context leaked between threads.")


class TestTraceContext:
    """
    Tests the functionality of the trace_context context manager and decorator.
    """

    def test_generates_trace_id(self):
        """
        Test that the context manager generates a new trace_id when none is provided.
        """
        assert trace_id_var.get() is None
        with trace_context(origin='test_origin'):
            generated_id = trace_id_var.get()
            assert generated_id is not None
            assert isinstance(uuid.UUID(generated_id), uuid.UUID)
        assert trace_id_var.get() is None

    def test_uses_provided_trace_id(self):
        """
        Test that the context manager uses the trace_id that is passed to it.
        """
        provided_id = str(uuid.uuid4())
        assert trace_id_var.get() is None
        with trace_context(origin='test_origin', trace_id=provided_id):
            assert trace_id_var.get() == provided_id
        assert trace_id_var.get() is None

    def test_handles_invalid_trace_id(self):
        """
        Test that the context manager generates a new trace_id if the provided one is invalid.
        """
        invalid_id = 'not-a-uuid'
        assert trace_id_var.get() is None
        with trace_context(origin='test_origin', trace_id=invalid_id):
            generated_id = trace_id_var.get()
            assert generated_id is not None
            assert generated_id != invalid_id
            assert isinstance(uuid.UUID(generated_id), uuid.UUID)
        assert trace_id_var.get() is None

    def test_resets_context_on_exception(self):
        """
        Test that context variables are reset even if an exception is raised.
        """
        assert trace_id_var.get() is None
        with pytest.raises(ValueError):
            with trace_context(origin='test_exception'):
                raise ValueError("Test exception")
        assert trace_id_var.get() is None

    def test_as_decorator(self):
        """
        Test that the trace_context decorator sets and clears context correctly.
        """

        @trace_context(origin='test_decorator')
        def my_function():
            assert trace_id_var.get() is not None
            assert origin_var.get() == 'test_decorator'

        assert trace_id_var.get() is None
        my_function()
        assert trace_id_var.get() is None

    def test_decorator_with_provided_id(self):
        """
        Test that the trace_context decorator uses a provided trace_id.
        """
        provided_id = str(uuid.uuid4())

        @trace_context(origin='test_decorator_id', trace_id=provided_id)
        def my_function():
            assert trace_id_var.get() == provided_id
            assert origin_var.get() == 'test_decorator_id'

        assert trace_id_var.get() is None
        my_function()
        assert trace_id_var.get() is None

    def test_nested_trace_context(self):
        """
        Test that nested trace_context managers work correctly, restoring the previous context.
        """
        outer_id = str(uuid.uuid4())
        with trace_context(origin='outer', trace_id=outer_id):
            assert trace_id_var.get() == outer_id
            assert origin_var.get() == 'outer'

            with trace_context(origin='inner'):
                inner_id = trace_id_var.get()
                assert inner_id is not None
                assert inner_id != outer_id
                assert origin_var.get() == 'inner'

            assert trace_id_var.get() == outer_id
            assert origin_var.get() == 'outer'

        assert trace_id_var.get() is None
