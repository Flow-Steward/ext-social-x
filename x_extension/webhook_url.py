"""Validate the operator-supplied Core callback capability without retaining it."""

import hashlib
from urllib.parse import urlsplit

from .client import XError


def callback_url_hash(url: object) -> str:
    if not isinstance(url, str) or len(url) > 200:
        raise XError(
            "invalid_payload",
            "A Core-issued HTTPS callback URL of at most 200 characters is required.",
        )
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.port is not None
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise XError(
            "invalid_payload",
            "The callback URL must be public HTTPS without a port, credentials or fragment.",
        )
    return hashlib.sha256(url.encode()).hexdigest()
