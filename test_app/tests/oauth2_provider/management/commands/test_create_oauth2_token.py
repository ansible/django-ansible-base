# Python
import random
import string
from io import StringIO

import pytest

# Django
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from ansible_base.oauth2_provider.models import OAuth2AccessToken

User = get_user_model()


@pytest.mark.django_db
class TestOAuth2CreateCommand:
    def test_no_user_option(self):
        with StringIO() as out:
            out = StringIO()
            with pytest.raises(CommandError) as excinfo:
                call_command('create_oauth2_token', stdout=out)
            assert 'Username not supplied.' in str(excinfo.value)

    def test_non_existing_user(self):
        with StringIO() as out:
            fake_username = ''
            while fake_username == '' or User.objects.filter(username=fake_username).exists():
                fake_username = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(6))
            arg = '--user=' + fake_username
            with pytest.raises(CommandError) as excinfo:
                call_command('create_oauth2_token', arg, stdout=out)
            assert 'The user does not exist.' in str(excinfo.value)

    def test_correct_user(self, random_user):
        user_username = random_user.username
        with StringIO() as out:
            arg = '--user=' + user_username
            call_command('create_oauth2_token', arg, stdout=out)
            generated_token = out.getvalue().strip()
            assert OAuth2AccessToken.objects.filter(user=random_user, token=generated_token).count() == 1
            assert OAuth2AccessToken.objects.get(user=random_user, token=generated_token).scope == 'write'
