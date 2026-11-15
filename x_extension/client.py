"""Bounded official X transport: one attempt, no provider-body leakage."""

from __future__ import annotations

import json
from time import monotonic
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request

from flowsteward_extension_sdk import open_pinned_url
from flowsteward_extension_sdk.http import parse_retry_after

from .deadlines import network_timer

RESPONSE_LIMIT = 2 * 1024 * 1024


class XError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        unknown: bool = False,
        retry_after: float | None = None,
        details: dict[str, Any] | None = None,
        effect_possible: bool = False,
    ):
        super().__init__(message)
        self.code = code
        self.unknown = unknown
        self.retry_after = retry_after
        self.details = details or {}
        self.effect_possible = effect_possible


class XClient:
    def __init__(self, token: str, *, deadline: float | None = None):
        if not isinstance(token, str) or not token.strip() or any(ord(c) < 33 for c in token):
            raise XError(
                "authorization_required", "A current host-managed X access token is required."
            )
        self.token = token
        self.deadline = deadline if deadline is not None else monotonic() + 75

    def request(self, method: str, path: str, *, body: dict | None = None) -> dict[str, Any]:
        if not path.startswith("/2/") or ".." in path or "#" in path:
            raise XError("invalid_payload", "Unsupported X API endpoint.")
        mutation = method not in {"GET", "HEAD"}
        request = Request(
            "https://api.x.com" + path,
            data=json.dumps(body, allow_nan=False).encode() if body is not None else None,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method=method,
        )
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise XError(
                "provider_unavailable",
                "X operation deadline exhausted before the next request; no request was sent.",
            )
        request_budget = min(25.0, remaining)
        try:
            with (
                network_timer(request_budget),
                open_pinned_url(
                    request, timeout_seconds=request_budget, purpose="X API"
                ) as response,
            ):
                raw = response.read(RESPONSE_LIMIT + 1)
            if len(raw) > RESPONSE_LIMIT:
                raise XError(
                    "response_too_large",
                    "X response exceeds the safe limit.",
                    unknown=mutation,
                    effect_possible=mutation,
                )
            data = json.loads(raw) if raw.strip() else {}
            if not isinstance(data, dict):
                raise ValueError("object required")
            return data
        except HTTPError as exc:
            code = {
                400: "invalid_payload",
                401: "authorization_required",
                402: "credits_required",
                403: "forbidden",
                404: "not_found",
                409: "invalid_payload",
                429: "rate_limited",
            }.get(exc.code, "provider_unavailable")
            definitive_rejection = exc.code in {400, 401, 402, 403, 404, 409, 413, 415, 422, 429}
            raise XError(
                code,
                "X API request failed; check access, credits and provider status.",
                unknown=mutation and not definitive_rejection,
                effect_possible=mutation and not definitive_rejection,
                retry_after=parse_retry_after(exc.headers.get("Retry-After"))
                if exc.headers
                else None,
            ) from None
        except XError:
            raise
        except (OSError, ValueError, TimeoutError):
            raise XError(
                "timeout_unknown" if mutation else "provider_unavailable",
                "X request outcome is unknown; inspect provider state before retrying."
                if mutation
                else "X API is temporarily unavailable.",
                unknown=mutation,
                effect_possible=mutation,
            ) from None
