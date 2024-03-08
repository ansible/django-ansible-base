import pytest
from django.test import override_settings
from rest_framework.reverse import reverse

from ansible_base.lib.utils.settings import get_setting
from ansible_base.rest_pagination.default_paginator import DefaultPaginator
from test_app.models import Organization


@pytest.mark.django_db
def test_default_paginator_pagination_backend_output_correct_total_count():
    num_orgs = 10
    organizations = []
    for index in range(num_orgs):
        organizations.append(Organization.objects.create(name=f"Test Organization {index}"))

    queryset = Organization.objects.all()
    assert queryset.count() == num_orgs
    p = DefaultPaginator().django_paginator_class(queryset, 10)
    p.page(1)
    assert p.count == num_orgs


max_page_size = 5


@pytest.mark.parametrize(
    "num_orgs, page_size_query_param, expected_results",
    [
        (10, 6, max_page_size),  # Asked for more than max page size allows should get max
        (4, 5, 4),  # Asked for ok page size but there were less items, should get all items
        (8, 3, 3),  # Asked for smaller page size with plenty of items, should get the page size
    ],
)
@pytest.mark.django_db
@override_settings(MAX_PAGE_SIZE=max_page_size)
def test_default_paginator_ensure_proper_result_length(num_orgs, page_size_query_param, expected_results, admin_api_client):
    # Create more orgs than we need
    organizations = []
    for index in range(num_orgs):
        organizations.append(Organization.objects.create(name=f"Test Organization {index}"))

    assert get_setting('MAX_PAGE_SIZE', None) == max_page_size

    # Request with the page_size equal to the max with the variation
    url = f"{reverse('organization-list')}?page_size={page_size_query_param}"
    response = admin_api_client.get(url)

    # If we variation was not negative than we expect the max_page_size, if its less than we should get less
    assert len(response.data['results']) == expected_results


@pytest.mark.parametrize("with_page_size", [(True), (False)])
def test_default_paginator_count_disabled(with_page_size, admin_api_client):
    url = f"{reverse('organization-list')}?count_disabled=True"
    if with_page_size:
        url = f'{url}&page_size=10'
    response = admin_api_client.get(url)
    assert 'count' not in response.data


@pytest.mark.parametrize(
    "page_index",
    [
        (1),
        (2),
        (3),
        (4),
        (5),
    ],
)
def test_default_paginator_next_and_previous_pages(page_index, admin_api_client):
    num_orgs = 5
    for org_index in range(num_orgs):
        Organization.objects.create(name=f"Test Organization {org_index}")

    base_url = f"{reverse('organization-list')}"
    page_url = f"{base_url}?page={page_index}&page_size=1"
    next_page = f"{base_url}?page={page_index+1}&page_size=1"
    previous_page = f"{base_url}?page={page_index-1}&page_size=1"
    if page_index == 1:
        previous_page = None
    elif page_index == 2:
        # Page 2 is a special case because it will not append page=1 to the results
        previous_page = f"{base_url}?page_size=1"
    elif page_index == 5:
        next_page = None

    response = admin_api_client.get(page_url)
    assert response.data['count'] == 5  # There are 5 orgs created
    assert response.data['next'] == next_page
    assert response.data['previous'] == previous_page
    assert 'results' in response.data and len(response.data['results']) == 1
