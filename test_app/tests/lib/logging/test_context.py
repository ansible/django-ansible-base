import random
import threading
import time
import unittest

from ansible_base.lib.logging.context import trace_id_var


class TestContextSafety(unittest.TestCase):
    def test_trace_id_is_thread_safe(self):
        """
        Verify that the trace_id context variable is thread-safe.
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
