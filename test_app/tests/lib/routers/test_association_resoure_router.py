import pytest
from django.urls import reverse

from ansible_base.lib.routers import AssociationResourceRouter
from test_app import views
from test_app.models import Cow, Inventory, Organization, RelatedFieldsTestModel, Team, User
from test_app.router import router
from test_app.views import TeamViewSet


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
        r'organizations',
        views.OrganizationViewSet,
        basename='organization',
    )
    validate_expected_url_pattern_names(router, ['organization-list', 'organization-detail'])


def test_association_router_basic_viewset_no_basename():
    class OrganizationViewSetWithQueryset(views.OrganizationViewSet):
        queryset = Organization.objects.all()

    router = AssociationResourceRouter()
    router.register(r'organizations', OrganizationViewSetWithQueryset)
    validate_expected_url_pattern_names(router, ['organization-list', 'organization-detail'])


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
    related_model = RelatedFieldsTestModel.objects.create()
    assert related_model.users.count() == 0

    url = reverse('related_fields_test_model-users-associate', kwargs={'pk': related_model.pk})
    response = admin_api_client.post(url, data=data, format='json')
    assert response.status_code == 400
    assert response.json().get('instances') == response_instances


def test_association_router_associate_existing_item(db, admin_api_client, random_user):
    related_model = RelatedFieldsTestModel.objects.create()
    related_model.users.add(random_user)
    assert related_model.users.count() == 1
    assert User.objects.get(pk=random_user.pk) is not None

    url = reverse('related_fields_test_model-users-associate', kwargs={'pk': related_model.pk})
    response = admin_api_client.post(url, data={'instances': [random_user.pk]}, format='json')
    assert response.status_code == 204


def test_association_router_disassociate(db, admin_api_client, randname, organization):
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
        ({'instances': [-1]}, ['Invalid pk "-1" - object does not exist or is not associated with parent object.']),
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
    related_model = RelatedFieldsTestModel.objects.create()
    assert related_model.more_teams.count() == 0

    url = reverse('related_fields_test_model-more_teams-disassociate', kwargs={'pk': related_model.pk})
    response = admin_api_client.post(url, data=data, format='json')
    assert response.status_code == 400
    assert response.json().get('instances') == response_instances


def test_association_router_disassociate_something_not_associated(db, admin_api_client, organization):
    related_model = RelatedFieldsTestModel.objects.create()
    team1 = Team.objects.create(name='Team 1', organization=organization)
    team2 = Team.objects.create(name='Team 2', organization=organization)
    team3 = Team.objects.create(name='Team 3', organization=organization)
    related_model.more_teams.add(team1)

    url = reverse('related_fields_test_model-more_teams-disassociate', kwargs={'pk': related_model.pk})
    response = admin_api_client.post(url, data={'instances': [team1.pk, team2.pk, team3.pk]}, format='json')
    assert response.status_code == 400
    assert response.json().get('instances') == [f'Invalid pk "{team2.pk}" - object does not exist or is not associated with parent object.']


def test_association_router_related_viewset_reverse_mapings(db):
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
        'my_test_basename-teams-list',
    ]
    validate_expected_url_pattern_names(router, expected_urls)


def test_association_router_related_viewset_m2m_mapings(db, user):
    router = AssociationResourceRouter()
    obj = RelatedFieldsTestModel.objects.create()
    obj.users.add(user)
    router.register(
        r'rel_models',
        views.RelatedFieldsTestModelViewSet,
        related_views={
            'users': (views.UserViewSet, 'users'),
        },
        basename='rel_test_basename',
    )
    expected_urls = [
        'rel_test_basename-detail',
        'rel_test_basename-list',
        'rel_test_basename-users-list',
        'rel_test_basename-users-associate',
        'rel_test_basename-users-disassociate',
    ]
    validate_expected_url_pattern_names(router, expected_urls)


def test_sublist_filtering(organization, admin_api_client):
    obj = Inventory.objects.create(name='first-one', organization=organization)
    Inventory.objects.create(name='another-one', organization=organization)
    url = reverse('organization-inventories-list', kwargs={'pk': organization.pk})

    # sanity, without filtering, we get the 2 inventories
    response = admin_api_client.get(url)
    assert response.status_code == 200, response.data
    assert response.data['count'] == 2

    # now we can filter by name for only the inventory object
    response = admin_api_client.get(url, data={'name': obj.name})
    assert response.status_code == 200, response.data
    assert response.data['count'] == 1


def test_sublist_override_filtering(organization, inventory, user_api_client, user, org_member_rd):
    "The organization cow list shows all cows regardless of view permission"
    cow_url = reverse('organization-cows-list', kwargs={'pk': organization.pk})
    inventory_url = reverse('organization-inventories-list', kwargs={'pk': organization.pk})
    Cow.objects.create(organization=organization)

    # User needs view permission to the parent object
    org_member_rd.give_permission(user, organization)

    # User can not view any inventories because they do not have view permission
    # The cow sublist is not set up this way in test_app, just for testing
    response = user_api_client.get(cow_url)
    assert response.status_code == 200, response.data
    assert response.data['count'] == 1
    response = user_api_client.get(inventory_url)
    assert response.status_code == 200, response.data
    assert response.data['count'] == 0

    # Assures that rest_filters still works
    response = user_api_client.get(cow_url, data={'id': 12341234})
    assert response.status_code == 200, response.data
    assert response.data['count'] == 0


@pytest.mark.parametrize('method', ['GET', 'PUT', 'POST', 'DELETE'])
def test_related_detail_actions_get_scrubed(organization, method, admin_api_client):
    cow = Cow.objects.create(organization=organization)
    # raise Exception(reverse('organization-cows-list', kwargs={'pk': organization.pk}))
    url = f'/api/v1/organizations/{organization.pk}/cows/{cow.pk}/'
    # Can not use the reverse function like this, because post-fix, the view does not exist
    # url = reverse('organization-cows-detail', kwargs={'pk': organization.pk, 'cows': cow.pk})
    if method in ('PUT', 'POST'):
        response = admin_api_client.get(url, data={})
    else:
        response = admin_api_client.get(url)
    assert response.status_code == 404


@pytest.mark.parametrize('method', ['GET', 'PUT', 'POST', 'DELETE'])
def test_related_custom_actions_get_scrubed(organization, method, admin_api_client):
    cow = Cow.objects.create(organization=organization)
    url = f'/api/v1/organizations/{organization.pk}/cows/{cow.pk}/cowsay/'
    # Can not use the reverse function like this, because post-fix, the view does not exist
    # url = reverse('organization-cows-cowsay', kwargs={'pk': organization.pk, 'cows': cow.pk})
    if method in ('PUT', 'POST'):
        response = admin_api_client.get(url, data={})
    else:
        response = admin_api_client.get(url)
    assert response.status_code == 404


def test_autogen_viewset_attributes():
    sublist_viewset = None
    for url, viewset, view_name in router.registry:
        if view_name == 'organization-teams':
            sublist_viewset = viewset
            break
    if not sublist_viewset:
        raise Exception(f'Failed to find organization teams list in {router.registry}')

    for removed_method in ('retrieve', 'partial_update', 'destroy'):
        assert hasattr(TeamViewSet, removed_method)
        assert not hasattr(sublist_viewset, removed_method)

        assert removed_method in dir(TeamViewSet)
        assert removed_method not in dir(sublist_viewset)
