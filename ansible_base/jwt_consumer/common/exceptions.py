from rest_framework.exceptions import APIException


class InvalidService(Exception):
    def __init__(self, service):
        super().__init__(f"This authentication class requires {service}.")


class InvalidTokenException(APIException):
    status_code = 498
    status_text = "Invalid Token"
    default_detail = "Invalid or expired token."
    default_code = "invalid_token"
