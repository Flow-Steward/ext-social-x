"""NFC and twitter-text compatible ordinary 280 weighted-character posts."""

from __future__ import annotations

import unicodedata
from urllib.parse import urlsplit

from twitter_text import extract_urls, parse_tweet

from .client import XError


def validate_post(text: object, canonical_url: object = None) -> dict:
    if not isinstance(text, str) or len(text) > 100_000:
        raise XError("invalid_payload", "Post text must be a bounded string.")
    value = unicodedata.normalize("NFC", text)
    if canonical_url:
        if not isinstance(canonical_url, str) or len(canonical_url) > 4096:
            raise XError("invalid_payload", "Article link must be a bounded HTTP(S) URL.")
        url = urlsplit(canonical_url)
        if (
            url.scheme not in {"https", "http"}
            or not url.hostname
            or url.username
            or url.password
            or any(c.isspace() for c in canonical_url)
        ):
            raise XError("invalid_payload", "Article link must be an intact HTTP(S) URL.")
        if canonical_url not in set(extract_urls(value)):
            value = value.rstrip() + "\n" + canonical_url
    parsed = parse_tweet(value)
    valid = bool(value.strip()) and parsed.valid and parsed.weightedLength <= 280
    return {
        "text": value,
        "weighted_length": parsed.weightedLength,
        "valid": valid,
        "errors": [] if valid else ["Post must contain valid text within 280 weighted characters."],
    }
