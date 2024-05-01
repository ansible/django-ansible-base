from django.urls import reverse
from rest_framework.decorators import action
from rest_framework.response import Response

from ansible_base.oauth2_provider.models import OAuth2AccessToken
from ansible_base.oauth2_provider.serializers import OAuth2TokenSerializer


class DABOAuth2UserViewsetMixin:
    """
    This mixin provides several actions to expose as sub-urls for a given user PK.
    """

    def extra_related_fields(self, obj) -> dict[str, str]:
        fields = super().extra_related_fields(obj)
        fields['personal_tokens'] = reverse(f'{self.basename}-personal-tokens-list', kwargs={"pk": obj.pk})
        return fields

    @action(detail=True, methods=["get"], url_name="personal-tokens-list")
    def personal_tokens(self, request, pk=None):
        tokens = OAuth2AccessToken.objects.filter(application__isnull=True, user=pk)
        page = self.paginate_queryset(tokens)
        if page is not None:
            serializer = OAuth2TokenSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = OAuth2TokenSerializer(tokens, many=True)
        return Response(serializer.data)
