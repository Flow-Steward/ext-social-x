"""Safe SDK error envelopes."""

from typing import Any


def error_payload(code: str, message: str, *, unknown: bool = False) -> dict[str, str]:
    return {"code": "timeout_unknown" if unknown else code, "message": message}


def failure(code: str, message: str, *, unknown: bool = False, **extra: Any) -> dict:
    error = error_payload(code, message, unknown=unknown)
    return {
        "ok": False,
        "result": {},
        "error_code": error["code"],
        "error": message,
        "errors": [error],
        "external_effect_status": "timeout_unknown" if unknown else "failed",
        "definitely_no_external_effect": not unknown,
        **extra,
    }
