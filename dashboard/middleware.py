"""Ensure authenticated portal pages always show fresh DB data after approvals."""

from __future__ import annotations


class NoStoreAuthenticatedMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return response

        content_type = response.get("Content-Type", "")
        if "text/html" in content_type or "text/csv" in content_type:
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
        return response
