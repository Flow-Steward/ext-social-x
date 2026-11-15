"""Declared connection-scoped state and neutral host callback setup receipts."""


def state_from_target(target: dict, connection_id: str) -> dict:
    for row in (target.get("project_state") or {}).get("items") or []:
        if (
            row.get("namespace") == "x_webhook"
            and row.get("state_key") == "registration"
            and row.get("connection_id") == connection_id
        ):
            return dict(row.get("value") or {})
    return {}


def state_response(state: dict, *, callback_outcome: str | None = None) -> dict:
    result = dict(state)
    if callback_outcome is not None:
        result["callback_setup"] = {"outcome": callback_outcome}
    return {
        "ok": True,
        "result": result,
        "project_state_updates": [
            {"namespace": "x_webhook", "state_key": "registration", "value": state}
        ],
    }
