from datetime import datetime

from django.db import connections
from rest_framework.response import Response

#from templated_app.version import get_aap_version
from ansible_base.django_template.views.api.v1.common import AnsibleBaseView
from ansible_base.lib.constants import STATUS_DEGRADED, STATUS_GOOD


def _get_db_connection_status(db_conn):
    try:
        db_conn.cursor()
        return {'db_connected': True}
    except Exception as e:
        # We only log the exception type because the message could contain sensitive information
        return {'db_connected': False, 'db_exception': type(e).__name__, 'status': STATUS_DEGRADED}


class PingView(AnsibleBaseView):
    permission_classes = []

    def get(self, request):
        current_time = datetime.now()
        response = {
#            "version": get_aap_version(),
            "pong": str(current_time),
            "status": STATUS_GOOD,
        }

        # Attempt a db connection
        db_info = _get_db_connection_status(connections['default'])
        response.update(db_info)

        return Response(response)
