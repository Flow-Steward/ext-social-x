"""Declared connection-scoped remote lifecycle records."""


def state_from_target(target: dict, connection_id: str) -> dict:
    for row in (target.get("project_state") or {}).get("items") or []:
        if (
            row.get("namespace") == "x_webhook"
            and row.get("state_key") == "registration"
            and row.get("connection_id") == connection_id
        ):
            return dict(row.get("value") or {})
    return {}


def state_response(state: dict, *, error: dict | None = None) -> dict:
    # ok means the lifecycle record was processed. Callers must inspect configured/status.
    result = {
        **state,
        "configured": state.get("status") == "ready",
        "reconciliation_required": state.get("status")
        in {"unknown", "setup_failed", "remove_failed", "not_ready", "webhook_created"},
    }
    if error:
        result["error"] = error
    return {
        "ok": True,
        "result": result,
        "project_state_updates": [
            {"namespace": "x_webhook", "state_key": "registration", "value": state}
        ],
    }
