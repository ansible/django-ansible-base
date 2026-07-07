from django.http import JsonResponse
from django.views import View


class NotFoundView(View):
    """Return a JSON 404 for unhandled paths."""

    def dispatch(self, request, *args, **kwargs):
        return JsonResponse({"error": "not_found"}, status=404)
