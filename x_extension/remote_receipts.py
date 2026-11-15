"""Closed provider response evidence required for destructive recovery decisions."""

from .client import XError


def _no_errors(payload: dict) -> bool:
    errors = payload.get("errors", [])
    return isinstance(errors, list) and not errors


def complete_list(payload: dict, *, saturation_limit: int | None = None) -> list[dict]:
    rows = payload.get("data")
    if (
        not _no_errors(payload)
        or not isinstance(rows, list)
        or any(not isinstance(row, dict) for row in rows)
    ):
        raise XError(
            "provider_unavailable",
            "X list response is partial or malformed; reconciliation remains unknown.",
        )
    if "meta" in payload:
        meta = payload["meta"]
        if not isinstance(meta, dict):
            raise XError("provider_unavailable", "X list metadata is malformed.")
        if "result_count" in meta:
            count = meta["result_count"]
            if type(count) is not int or count < 0 or count != len(rows):
                raise XError("provider_unavailable", "X list result count is inconsistent.")
        if any(meta.get(key) for key in ["next_token", "pagination_token", "next_cursor", "next"]):
            raise XError(
                "provider_unavailable", "X list is incomplete; reconciliation remains unknown."
            )
    if saturation_limit is not None and len(rows) >= saturation_limit:
        raise XError(
            "provider_unavailable",
            "X subscription list may be truncated; reconciliation remains unknown.",
        )
    return rows


def confirmed_deletion(payload: dict) -> bool:
    data = payload.get("data")
    return _no_errors(payload) and isinstance(data, dict) and data.get("deleted") is True
