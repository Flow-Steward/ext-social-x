"""Safe SDK envelopes and host-owned setup marker validation."""

from typing import Any

from .client import XError


def failure(code: str, message: str, *, unknown: bool = False, **extra: Any) -> dict:
    return {
        "ok": False,
        "result": {},
        "error_code": code,
        "error": message,
        "errors": [{"code": code, "message": message}],
        "external_effect_status": "timeout_unknown" if unknown else "failed",
        "definitely_no_external_effect": not unknown,
        **extra,
    }


def require_callback_setup(target: dict, *, needs_attempt: bool = True) -> dict:
    setup = target.get("callback_setup")
    if (
        not isinstance(setup, dict)
        or setup.get("outcome") not in {"fresh", "unknown", "configured", "absent", "resumable"}
        or (
            needs_attempt
            and (not isinstance(setup.get("attempt_id"), str) or not setup["attempt_id"])
        )
    ):
        raise XError(
            "invalid_payload",
            "A host-owned callback setup intent is required; use the callback registration endpoint.",
        )
    return setup
