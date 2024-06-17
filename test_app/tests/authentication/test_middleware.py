from social_core.exceptions import AuthException

from ansible_base.authentication.middleware import SocialExceptionHandlerMiddleware


def test_social_exception_handler_mw():
    class Strategy:
        def setting(self, name):
            return "/"

    class Backend:
        def __init__(self):
            self.name = "test"

    class Request:
        def __init__(self):
            self.social_strategy = Strategy()
            self.backend = Backend()

    mw = SocialExceptionHandlerMiddleware(None)
    url = mw.get_redirect_uri(Request(), AuthException("test"))
    assert url == "/?auth_failed"
