from crum import impersonate
from django.core.management.base import BaseCommand

from test_app.models import EncryptionModel, Organization, Team, User


class Command(BaseCommand):
    help = 'Creates demo data for development.'

    def handle(self, *args, **kwargs):
        if Organization.objects.exists():
            print('It looks like you already have data loaded, great!')
            return

        awx = Organization.objects.create(name='AWX_community')
        galaxy = Organization.objects.create(name='Galaxy_community')

        spud = User.objects.create(username='angry_spud')
        bull_bot = User.objects.create(username='ansibullbot')

        with impersonate(spud):
            Team.objects.create(name='awx_docs', organization=awx)
            Team.objects.create(name='awx_devs', organization=awx)
            EncryptionModel.objects.create(name='foo', testing1='should not show this value!!', testing2='this value should also not be shown!')
            Organization.objects.create(name='Operator_community')

        with impersonate(bull_bot):
            Team.objects.create(name='community.general maintainers', organization=galaxy)

        print('Finished creating demo data!')
