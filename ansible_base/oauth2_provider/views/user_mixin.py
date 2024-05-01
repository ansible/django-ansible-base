from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.decorators import action
from rest_framework.response import Response

from ansible_base.lib.abstract_models.common import get_cls_view_basename
from ansible_base.oauth2_provider.models import OAuth2AccessToken
from ansible_base.oauth2_provider.serializers import OAuth2TokenSerializer


class DABOAuth2UserViewsetMixin:
    """
    This mixin provides several actions to expose as sub-urls for a given user PK.
    """

    def extra_related_fields(self, obj) -> dict[str, str]:
        fields = super().extra_related_fields(obj)
        user_basename = get_cls_view_basename(get_user_model())
        fields['personal_tokens'] = reverse(f'{user_basename}-personal-tokens-list', kwargs={"pk": obj.pk})
        fields['authorized_tokens'] = reverse(f'{user_basename}-authorized-tokens-list', kwargs={"pk": obj.pk})
        return fields

    def _user_token_response(self, request, application_isnull, pk):
        tokens = OAuth2AccessToken.objects.filter(application__isnull=application_isnull, user=pk)
        page = self.paginate_queryset(tokens)
        if page is not None:
            serializer = OAuth2TokenSerializer(page, many=True, context={"request": request})
            return self.get_paginated_response(serializer.data)

        serializer = OAuth2TokenSerializer(tokens, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_name="personal-tokens-list")
    def personal_tokens(self, request, pk=None):
        return self._user_token_response(request, True, pk)

    @action(detail=True, methods=["get"], url_name="authorized-tokens-list")
    def authorized_tokens(self, request, pk=None):
        return self._user_token_response(request, False, pk)
