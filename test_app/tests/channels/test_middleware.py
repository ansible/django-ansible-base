from unittest.mock import AsyncMock, Mock, patch

import pytest

import ansible_base.channels.middleware as middleware


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_middleware_auth_pass(local_authenticator, user):
    inner = AsyncMock()
    auth = middleware.DrfAuthMiddleware(inner)
    scope = {"session": {}, "headers": [(b"Authorization", b"Basic dXNlcjpwYXNzd29yZA==")]}
    await auth(scope, Mock(), Mock())

    assert scope["user"]
    inner.assert_awaited_once()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@patch('ansible_base.channels.middleware.WebsocketDenier')
async def test_middleware_auth_denied(denier_class, local_authenticator, user):
    denier = AsyncMock()
    denier_class.return_value = denier

    inner = AsyncMock()
    auth = middleware.DrfAuthMiddleware(inner)
    scope = {"session": {}, "headers": {}}
    await auth(scope, Mock(), Mock())

    assert "user" not in scope
    inner.assert_not_awaited()
    denier.assert_awaited_once()
