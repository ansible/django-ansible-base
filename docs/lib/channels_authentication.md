# Channels Authentication
Django channels claims to support standard Django authentication out-of-the box for HTTP and WebSocket consummers. But its `AuthMiddleware` only supports Django authentication when the user details are stored in the session.

django-ansible-base provides a channels middleware to support Django authentication backed by AUTHENTICATION_BACKENDS in settings.py.

## Settings
There is no requirement to alter any configuration in settings.py. You only need to import ansible_base.lib.channels.middleware into your project. It however looks for settings.AUTHENTICATION_BACKENDS for possible authenticators to authenticate the websocket connection.

## Usage
`ansible_base.lib.channels.middleware` has `DrfAuthMiddleware` which expands `channels.auth.AuthMiddleware` functionalities to support sessions and other authentication methods. It requires `CookieMiddleware` and `SessionMiddleware`. For convenience `DrfAuthMiddlewareStack` is provided to included all three.

To use the middleware, wrap it around the appropriate level of consumer in your `asgi.py`:

```
from django.urls import re_path

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator

from ansible_base.lib.channels.middleware import DrfAuthMiddlewareStack

from myapp import consumers

application = ProtocolTypeRouter({

    "websocket": AllowedHostsOriginValidator(
        DrfAuthMiddlewareStack(
            URLRouter([
                re_path(r"^front(end)/$", consumers.AsyncChatConsumer.as_asgi()),
            ])
        )
    ),

})
```

While you can wrap the middleware around each consumer individually, it’s recommended you wrap it around a higher-level application component, like in this case the URLRouter.

Note that the DrfAuthMiddleware will only work on protocols that provide HTTP headers in their scope - by default, this is HTTP and WebSocket.

If the user can be retrieved from the stored session or by any backend in `settings.AUTHENTICATION_BACKEND`, the user is stored in `scope["user"]`. Othwerwise the websocket connection is denied and closed with return code 403.

If the authentication succeeded with a valid user, your consumer code can access it use `self.scope["user"]` to further assert the role permission.
