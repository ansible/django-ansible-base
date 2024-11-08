# Django
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand, CommandError

from ansible_base.oauth2_provider.serializers import OAuth2TokenSerializer

User = get_user_model()


class Command(BaseCommand):
    """Command that creates an OAuth2 token for a certain user. Returns the value of created token."""

    help = 'Creates an OAuth2 token for a user.'

    def add_arguments(self, parser):
        parser.add_argument('--user', dest='user', type=str)

    def handle(self, *args, **options):
        if not options['user']:
            raise CommandError('Username not supplied. Usage: create_oauth2_token --user=username.')
        try:
            user = User.objects.get(username=options['user'])
        except ObjectDoesNotExist:
            raise CommandError('The user does not exist.')
        config = {'user': user, 'scope': 'write'}
        serializer_obj = OAuth2TokenSerializer()

        class FakeRequest(object):
            def __init__(self):
                self.user = user

        serializer_obj.context['request'] = FakeRequest()
        serializer_obj.create(config)
        self.stdout.write(serializer_obj.unencrypted_token)
