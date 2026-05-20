import os
import threading

from django.apps import AppConfig


class TestAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'test_app'

    def ready(self):
        # RUN_MAIN is set only in the actual server process, not the reloader parent
        if os.environ.get('RUN_MAIN') != 'true':
            return
        from test_app import otlp_server

        t = threading.Thread(target=otlp_server.start, daemon=True)
        t.start()
