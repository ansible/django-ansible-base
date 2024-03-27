#  Copyright 2024 Red Hat, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

from unittest.mock import AsyncMock, Mock, patch

import pytest

import ansible_base.lib.channels.middleware as middleware


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
@patch('ansible_base.lib.channels.middleware.WebsocketDenier')
async def test_middleware_auth_denied(denier_class, system_user, local_authenticator, user):
    denier = AsyncMock()
    denier_class.return_value = denier

    inner = AsyncMock()
    auth = middleware.DrfAuthMiddleware(inner)
    scope = {"session": {}, "headers": {}}
    await auth(scope, Mock(), Mock())

    assert "user" not in scope
    inner.assert_not_awaited()
    denier.assert_awaited_once()
