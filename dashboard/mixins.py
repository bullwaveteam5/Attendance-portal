from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.views import LoginView
from django.http import JsonResponse

from attendance.location import LocationVerificationError, log_portal_access, verify_office_access
from attendance.models import OfficeSettings


class OfficeLocationLoginMixin:
    """Validate GPS geofence / office IP before completing portal login."""

    def _wants_json(self) -> bool:
        return self.request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def _run_office_verification(self):
        try:
            ctx = verify_office_access(
                self.request,
                latitude=self.request.POST.get("latitude"),
                longitude=self.request.POST.get("longitude"),
            )
            return ctx, None
        except LocationVerificationError as exc:
            lat = lon = None
            try:
                if self.request.POST.get("latitude") not in (None, ""):
                    lat = float(self.request.POST.get("latitude"))
                if self.request.POST.get("longitude") not in (None, ""):
                    lon = float(self.request.POST.get("longitude"))
            except (TypeError, ValueError):
                lat = lon = None
            log_portal_access(
                self.request,
                event_type="login",
                success=False,
                username=self.request.POST.get("username", ""),
                failure_reason=str(exc),
                latitude=lat,
                longitude=lon,
            )
            return None, str(exc)

    def _location_denied_response(self, error: str):
        """Return a clear block response without running password authentication."""
        if self._wants_json():
            return JsonResponse(
                {
                    "success": False,
                    "message": error,
                    "code": "outside_office",
                },
                status=403,
            )
        messages.error(self.request, error)
        form = self.get_form()
        return self.render_to_response(self.get_context_data(form=form))

    def post(self, request, *args, **kwargs):
        """Block login before password check if office GPS/IP verification fails."""
        if OfficeSettings.get_solo().requires_verification():
            ctx, error = self._run_office_verification()
            if error:
                return self._location_denied_response(error)
            self._office_verified_context = ctx
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        if self._wants_json():
            errors = form.non_field_errors()
            message = "; ".join(str(e) for e in errors) if errors else "Invalid Employee ID or password."
            return JsonResponse({"success": False, "message": message}, status=400)
        return super().form_invalid(form)

    def form_valid(self, form):
        ctx = getattr(self, "_office_verified_context", None)
        if ctx is None and OfficeSettings.get_solo().requires_verification():
            ctx, error = self._run_office_verification()
            if error:
                return self._location_denied_response(error)

        response = super().form_valid(form)
        if ctx:
            log_portal_access(
                self.request,
                event_type="login",
                success=True,
                user=self.request.user,
                username=self.request.user.employee_id,
                latitude=ctx.get("latitude"),
                longitude=ctx.get("longitude"),
                distance_m=ctx.get("distance_m"),
                client_ip=ctx.get("client_ip", ""),
                user_agent=ctx.get("user_agent", ""),
            )
        if self._wants_json():
            return JsonResponse({"success": True, "redirect": response.url})
        return response


class OfficeLocationLoginView(OfficeLocationLoginMixin, LoginView):
    pass
