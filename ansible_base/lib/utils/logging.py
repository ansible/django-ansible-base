import inspect
import uuid


def get_request_id(record):
    record.envoy_request_id = 'None'

    # Find the closets request in the call stack someday we should replace this with https://pypi.python.org/pypi/django-crequest
    frame = None
    try:
        for f in inspect.stack()[1:]:
            frame = f[0]
            code = frame.f_code

            user_request_id = None
            if code.co_varnames and code.co_varnames[0] == "request":
                user_request_id = frame.f_locals['request'].headers.get('x_request_id', None)
            elif code.co_name == 'Check' and len(code.co_varnames) > 1 and code.co_varnames[1]:
                user_request_id = frame.f_locals['request'].attributes.request.http.headers.get('x-request-id', None)

            if user_request_id:
                try:
                    request_id_uuid = uuid.UUID(str(user_request_id))
                    record.envoy_request_id = str(request_id_uuid)
                except ValueError:
                    record.envoy_request_id = 'Invalid'
                break
    finally:
        del frame

    return True
