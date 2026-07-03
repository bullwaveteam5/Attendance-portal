from __future__ import annotations

import os

from django.core.exceptions import ValidationError


def validate_upload_file(
    file,
    *,
    allowed_extensions: set[str],
    max_bytes: int = 5 * 1024 * 1024,
    label: str = "File",
) -> None:
    if not file:
        return
    if file.size > max_bytes:
        raise ValidationError(f"{label} must be smaller than {max_bytes // (1024 * 1024)} MB.")
    ext = os.path.splitext(file.name)[1].lower()
    if ext not in allowed_extensions:
        allowed = ", ".join(sorted(allowed_extensions))
        raise ValidationError(f"{label} type not allowed. Allowed: {allowed}")


DOCUMENT_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
PRAISE_EXTENSIONS = {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
