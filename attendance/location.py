from __future__ import annotations

import ipaddress
import math
import os
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.http import HttpRequest

    from .models import OfficeSettings


class LocationVerificationError(Exception):
    pass


def normalize_client_ip(ip: str) -> str:
    """Normalize IPv4-mapped IPv6 addresses (e.g. ::ffff:192.168.1.5 → 192.168.1.5)."""
    if not ip:
        return ip
    try:
        addr = ipaddress.ip_address(ip)
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
            return str(addr.ipv4_mapped)
    except ValueError:
        pass
    return ip


def get_client_ip(request: HttpRequest) -> str:
    trust_proxy = os.environ.get("TRUST_X_FORWARDED_FOR", "0") == "1"
    if trust_proxy:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded:
            return normalize_client_ip(forwarded.split(",")[0].strip())
    return normalize_client_ip(request.META.get("REMOTE_ADDR", ""))


def get_user_agent(request: HttpRequest) -> str:
    return (request.META.get("HTTP_USER_AGENT") or "")[:512]


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in meters between two WGS84 coordinates."""
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_coordinate(value, label: str) -> float:
    if value is None or value == "":
        raise LocationVerificationError(f"{label} is required.")
    try:
        return float(value)
    except (TypeError, ValueError, InvalidOperation) as exc:
        raise LocationVerificationError(f"Invalid {label.lower()}.") from exc


def _validate_gps_coordinates(latitude: float, longitude: float) -> None:
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise LocationVerificationError("Invalid GPS coordinates received.")
    if abs(latitude) < 0.01 and abs(longitude) < 0.01:
        raise LocationVerificationError("GPS location is required. Please allow location access in your browser.")


def verify_office_access(
    request: HttpRequest,
    *,
    latitude=None,
    longitude=None,
    settings: OfficeSettings | None = None,
) -> dict:
    """
    Validate client IP and/or GPS against office settings.
    Returns a context dict with coordinates, distance, IP, and user agent for logging.
    """
    from .models import OfficeSettings

    office = settings or OfficeSettings.get_solo()
    client_ip = get_client_ip(request)
    user_agent = get_user_agent(request)

    if not office.requires_verification():
        return {
            "latitude": None,
            "longitude": None,
            "distance_m": None,
            "client_ip": client_ip,
            "user_agent": user_agent,
        }

    parsed_lat: float | None = None
    parsed_lng: float | None = None
    distance_m: float | None = None

    if office.gps_verification_enabled:
        if office.latitude is None or office.longitude is None:
            raise LocationVerificationError("Office GPS coordinates are not configured. Contact your administrator.")
        parsed_lat = _parse_coordinate(latitude, "GPS latitude")
        parsed_lng = _parse_coordinate(longitude, "GPS longitude")
        _validate_gps_coordinates(parsed_lat, parsed_lng)
        distance_m = haversine_distance_m(
            parsed_lat,
            parsed_lng,
            float(office.latitude),
            float(office.longitude),
        )
        if distance_m > office.allowed_radius_meters:
            raise LocationVerificationError(
                "Your current location is not near the company office, so you cannot access "
                "the portal. Please try again when you are at the campus."
            )

    if office.ip_verification_enabled:
        if not office.get_allowed_ip_list():
            raise LocationVerificationError("Office public IP allowlist is not configured. Contact your administrator.")
        if not office.is_ip_allowed(client_ip):
            try:
                addr = ipaddress.ip_address(client_ip)
                is_loopback = addr.is_loopback
            except ValueError:
                is_loopback = False
            if is_loopback:
                raise LocationVerificationError(
                    "Access denied: you are using localhost. Connect to office WiFi and open the site "
                    "using your server IP (e.g. http://192.168.1.50:8000), not http://127.0.0.1."
                )
            raise LocationVerificationError(
                "Access denied: you must be connected to the office WiFi network. "
                f"(Detected IP: {client_ip or 'unknown'}. "
                "Turn on office WiFi and try again.)"
            )

    return {
        "latitude": parsed_lat,
        "longitude": parsed_lng,
        "distance_m": distance_m,
        "client_ip": client_ip,
        "user_agent": user_agent,
    }


def log_portal_access(
    request: HttpRequest,
    *,
    event_type: str,
    success: bool,
    user=None,
    username: str = "",
    failure_reason: str = "",
    latitude=None,
    longitude=None,
    distance_m=None,
    client_ip: str = "",
    user_agent: str = "",
) -> None:
    from .models import PortalAccessLog

    PortalAccessLog.objects.create(
        user=user if getattr(user, "pk", None) else None,
        username_attempt=username[:64],
        event_type=event_type,
        success=success,
        latitude=latitude,
        longitude=longitude,
        distance_m=distance_m,
        client_ip=client_ip or get_client_ip(request),
        user_agent=user_agent or get_user_agent(request),
        failure_reason=failure_reason[:255],
    )
