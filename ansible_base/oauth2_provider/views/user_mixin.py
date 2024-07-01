from django.contrib.auth import get_user_model
from rest_framework.decorators import action
from rest_framework.response import Response

from ansible_base.lib.abstract_models.common import get_cls_view_basename
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.oauth2_provider.models import OAuth2AccessToken
from ansible_base.oauth2_provider.serializers import OAuth2TokenSerializer


class DABOAuth2UserViewsetMixin:
    """
    This mixin provides several actions to expose as sub-urls for a given user PK.
    """

    def extra_related_fields(self, obj) -> dict[str, str]:
        fields = super().extra_related_fields(obj)
        user_basename = get_cls_view_basename(get_user_model())
        fields['personal_tokens'] = get_relative_url(f'{user_basename}-personal-tokens-list', kwargs={"pk": obj.pk})
        fields['authorized_tokens'] = get_relative_url(f'{user_basename}-authorized-tokens-list', kwargs={"pk": obj.pk})
        fields['tokens'] = get_relative_url(f'{user_basename}-tokens-list', kwargs={"pk": obj.pk})
        return fields

    def _user_token_response(self, request, filters, pk):
        tokens = OAuth2AccessToken.objects.filter(user=pk, **filters)
        page = self.paginate_queryset(tokens)
        if page is not None:
            serializer = OAuth2TokenSerializer(page, many=True, context={"request": request})
            return self.get_paginated_response(serializer.data)

        serializer = OAuth2TokenSerializer(tokens, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_name="personal-tokens-list")
    def personal_tokens(self, request, pk=None):
        filters = {'application__isnull': True}
        return self._user_token_response(request, filters, pk)

    @action(detail=True, methods=["get"], url_name="authorized-tokens-list")
    def authorized_tokens(self, request, pk=None):
        filters = {'application__isnull': False}
        return self._user_token_response(request, filters, pk)

    @action(detail=True, methods=["get"], url_name="tokens-list")
    def tokens(self, request, pk=None):
        return self._user_token_response(request, {}, pk)
