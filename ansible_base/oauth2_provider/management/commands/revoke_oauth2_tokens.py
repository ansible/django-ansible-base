# Django
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand, CommandError

from ansible_base.oauth2_provider.models import OAuth2AccessToken, OAuth2RefreshToken

User = get_user_model()


def revoke_tokens(token_list):
    for token in token_list:
        token.revoke()
        print('revoked {} {}'.format(token.__class__.__name__, token.token))


class Command(BaseCommand):
    """Command that revokes OAuth2 access tokens."""

    help = 'Revokes OAuth2 access tokens.  Use --all to revoke access and refresh tokens.'

    def add_arguments(self, parser):
        parser.add_argument('--user', dest='user', type=str, help='revoke OAuth2 tokens for a specific username')
        parser.add_argument('--all', dest='all', action='store_true', help='revoke OAuth2 access tokens and refresh tokens')

    def handle(self, *args, **options):
        if not options['user']:
            if options['all']:
                revoke_tokens(OAuth2RefreshToken.objects.filter(revoked=None))
            revoke_tokens(OAuth2AccessToken.objects.all())
        else:
            try:
                user = User.objects.get(username=options['user'])
            except ObjectDoesNotExist:
                raise CommandError('A user with that username does not exist.')
            if options['all']:
                revoke_tokens(OAuth2RefreshToken.objects.filter(revoked=None).filter(user=user))
            revoke_tokens(OAuth2AccessToken.objects.filter(user=user))
