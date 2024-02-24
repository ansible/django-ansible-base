import pytest
from django.urls import reverse

from ansible_base.lib.routers import AssociationResourceRouter
from test_app import views
from test_app.models import User


def validate_expected_url_pattern_names(router, expected_url_pattern_names):
    url_pattern_names = []
    for url_pattern in router.urls:
        url_pattern_names.append(url_pattern.name)

    expected_url_pattern_names.sort()
    url_pattern_names.sort()
    assert url_pattern_names == expected_url_pattern_names


def test_association_router_basic_viewset():
    router = AssociationResourceRouter()
    router.register(
        r'user',
        views.UserViewSet,
        basename='user',
    )
    validate_expected_url_pattern_names(router, ['user-list', 'user-detail'])


def test_association_router_basic_viewset_no_basename():
    class UserViewSetWithQueryset(views.UserViewSet):
        queryset = User.objects.all()

    router = AssociationResourceRouter()
    router.register(r'user', UserViewSetWithQueryset)
    validate_expected_url_pattern_names(router, ['user-list', 'user-detail'])


def test_association_router_associate_viewset_all_mapings():
    router = AssociationResourceRouter()
    router.register(
        r'related_model',
        views.RelatedFieldsTestModelViewSet,
        related_views={
            'teams': (views.TeamViewSet, 'teams'),
            'user': (views.UserViewSet, 'users'),
        },
        basename='my_test_basename',
    )
    expected_urls = [
        'my_test_basename-detail',
        'my_test_basename-list',
        'my_test_basename-teams-associate',
        'my_test_basename-teams-disassociate',
        'my_test_basename-teams-list',
        'my_test_basename-users-associate',
        'my_test_basename-users-disassociate',
        'my_test_basename-users-list',
    ]
    validate_expected_url_pattern_names(router, expected_urls)


def test_association_router_good_associate(db, admin_api_client, randname, organization):
    from test_app.models import RelatedFieldsTestModel, Team

    related_model = RelatedFieldsTestModel.objects.create()
    assert related_model.more_teams.count() == 0

    team = Team.objects.create(name=randname('team'), organization=organization)

    url = reverse('related_fields_test_model-more_teams-associate', kwargs={'pk': related_model.pk})
    response = admin_api_client.post(url, data={'instances': [team.pk]})
    assert response.status_code == 204

    related_model.refresh_from_db()
    assert related_model.more_teams.count() == 1


@pytest.mark.parametrize(
    "data,response_instances",
    [
        ({'instances': [-1]}, ['Invalid pk "-1" - object does not exist.']),
        ({'instances': ['a']}, ['Incorrect type. Expected pk value, received str.']),
        ({'instances': [True]}, ['Incorrect type. Expected pk value, received bool.']),
        ({'instances': {}}, 'Please pass in one or more instances to associate'),
        ({'instances': []}, 'Please pass in one or more instances to associate'),
        ({'instances': -1}, ['Expected a list of items but got type "int".']),
        ({}, ['This field is required.']),
        ({'not_an_instances': [1]}, ['This field is required.']),
    ],
)
def test_association_router_associate_bad_data(db, admin_api_client, data, response_instances):
    from test_app.models import RelatedFieldsTestModel

    related_model = RelatedFieldsTestModel.objects.create()
    assert related_model.users.count() == 0

    url = reverse('related_fields_test_model-users-associate', kwargs={'pk': related_model.pk})
    response = admin_api_client.post(url, data=data, format='json')
    assert response.status_code == 400
    assert response.json().get('instances') == response_instances


def test_association_router_associate_existing_item(db, admin_api_client, random_user):
    from test_app.models import RelatedFieldsTestModel

    related_model = RelatedFieldsTestModel.objects.create()
    related_model.users.add(random_user)
    assert related_model.users.count() == 1

    from test_app.models import User

    assert User.objects.get(pk=random_user.pk) is not None

    url = reverse('related_fields_test_model-users-associate', kwargs={'pk': related_model.pk})
    response = admin_api_client.post(url, data={'instances': [random_user.pk]}, format='json')
    assert response.status_code == 204


def test_association_router_disassociate(db, admin_api_client, randname, organization):
    from test_app.models import RelatedFieldsTestModel, Team

    team = Team.objects.create(name=randname('team'), organization=organization)

    related_model = RelatedFieldsTestModel.objects.create()
    related_model.more_teams.add(team)
    assert related_model.more_teams.count() == 1

    url = reverse('related_fields_test_model-more_teams-disassociate', kwargs={'pk': related_model.pk})
    response = admin_api_client.post(url, data={'instances': [team.pk]})
    assert response.status_code == 204

    related_model.refresh_from_db()
    assert related_model.more_teams.count() == 0


@pytest.mark.parametrize(
    "data,response_instances",
    [
        ({'instances': [-1]}, ['Invalid pk "-1" - object does not exist.']),
        ({'instances': ['a']}, ['Incorrect type. Expected pk value, received str.']),
        ({'instances': [True]}, ['Incorrect type. Expected pk value, received bool.']),
        ({'instances': {}}, 'Please pass in one or more instances to disassociate'),
        ({'instances': []}, 'Please pass in one or more instances to disassociate'),
        ({'instances': -1}, ['Expected a list of items but got type "int".']),
        ({}, ['This field is required.']),
        ({'not_an_instances': [1]}, ['This field is required.']),
    ],
)
def test_association_router_disassociate_bad_data(db, admin_api_client, data, response_instances):
    from test_app.models import RelatedFieldsTestModel

    related_model = RelatedFieldsTestModel.objects.create()
    assert related_model.more_teams.count() == 0

    url = reverse('related_fields_test_model-more_teams-disassociate', kwargs={'pk': related_model.pk})
    response = admin_api_client.post(url, data=data, format='json')
    assert response.status_code == 400
    assert response.json().get('instances') == response_instances


def test_association_router_disassociate_something_not_associated(db, admin_api_client, organization):
    from test_app.models import RelatedFieldsTestModel, Team

    related_model = RelatedFieldsTestModel.objects.create()
    team1 = Team.objects.create(name='Team 1', organization=organization)
    team2 = Team.objects.create(name='Team 2', organization=organization)
    team3 = Team.objects.create(name='Team 3', organization=organization)
    related_model.more_teams.add(team1)

    url = reverse('related_fields_test_model-more_teams-disassociate', kwargs={'pk': related_model.pk})
    response = admin_api_client.post(url, data={'instances': [team1.pk, team2.pk, team3.pk]}, format='json')
    assert response.status_code == 400
    assert response.json().get('instances') == (
        'Cannot disassociate these objects because they are not '
        f'all related to this object: {team2.pk}, {team3.pk}'
    )


def test_association_router_related_viewset_all_mapings(db):
    router = AssociationResourceRouter()
    router.register(
        r'organization',
        views.OrganizationViewSet,
        related_views={
            'teams': (views.TeamViewSet, 'teams'),
        },
        basename='my_test_basename',
    )
    expected_urls = [
        'my_test_basename-detail',
        'my_test_basename-list',
        'my_test_basename-teams-detail',
        'my_test_basename-teams-list',
    ]
    validate_expected_url_pattern_names(router, expected_urls)
