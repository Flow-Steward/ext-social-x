"""Read-only reconciliation of exact host-owned X resources after lost responses."""

from __future__ import annotations

import hashlib

from .client import XClient, XError
from .events import numeric_id
from .remote_receipts import complete_list
from .webhook_state import state_response

WEBHOOK_LIST = "/2/webhooks?webhook_config.fields=id,url,valid"


def _rows(app: XClient) -> list:
    rows = complete_list(app.request("GET", WEBHOOK_LIST))
    if any(
        not numeric_id(row.get("id"))
        or not isinstance(row.get("url"), str)
        or not isinstance(row.get("valid"), bool)
        for row in rows
    ):
        raise XError(
            "provider_unavailable",
            "X returned an incomplete webhook list; reconciliation is unresolved.",
        )
    return rows


def _url_hash(row: dict) -> str:
    url = row.get("url")
    return hashlib.sha256(url.encode()).hexdigest() if isinstance(url, str) else ""


def owned_webhook(app: XClient, state: dict) -> dict:
    matches = [
        row
        for row in _rows(app)
        if isinstance(row, dict) and row.get("id") == state.get("webhook_id")
    ]
    if len(matches) != 1:
        raise XError(
            "webhook_not_ready",
            "Saved X webhook is missing or ambiguous; reconcile the owned registration.",
        )
    owned = matches[0]
    if state.get("callback_url_hash") and _url_hash(owned) != state["callback_url_hash"]:
        raise XError(
            "webhook_not_ready", "Saved X webhook URL no longer matches this callback registration."
        )
    return owned


def _unknown(state: dict) -> dict:
    state["status"] = "unknown"
    return state_response(state, callback_outcome="unknown")


def _reconcile_webhook(state: dict, app: XClient, expected_hash: str) -> dict | None:
    rows = _rows(app)
    matches = [row for row in rows if _url_hash(row) == expected_hash]
    if len(matches) > 1:
        raise XError(
            "webhook_not_ready",
            "Multiple webhooks match this exact callback; operator reconciliation is required.",
        )
    saved_id = state.get("webhook_id")
    if saved_id:
        owned = [row for row in rows if row.get("id") == saved_id]
        if owned and (len(owned) != 1 or _url_hash(owned[0]) != expected_hash):
            raise XError("webhook_not_ready", "Saved webhook no longer matches the owned callback.")
        if not owned and matches:
            raise XError(
                "webhook_not_ready",
                "Another webhook cannot replace the saved owned ID without operator reconciliation.",
            )
    return matches[0] if matches else None


def status(state: dict, user: XClient, app: XClient, setup: dict, subject: str) -> dict:
    if state.get("account_user_id") and state["account_user_id"] != subject:
        raise XError(
            "invalid_connection",
            "Saved remote state belongs to a previous OAuth account; reconcile it using the original account.",
        )
    expected_hash = setup.get("callback_url_hash") or state.get("callback_url_hash")
    if expected_hash:
        try:
            webhook = _reconcile_webhook(state, app, expected_hash)
        except XError as exc:
            if exc.code == "webhook_not_ready":
                return _unknown(state)
            raise
        if webhook is None:
            state.clear()
            state.update(
                status="not_configured", account_user_id=subject, callback_url_hash=expected_hash
            )
            return state_response(state, callback_outcome="absent")
        state.update(
            webhook_id=webhook["id"], callback_url_hash=expected_hash, account_user_id=subject
        )
    elif state.get("webhook_id"):
        webhook = owned_webhook(app, state)
    else:
        return _unknown(state)
    listing = user.request(
        "GET", "/2/activity/subscriptions?user_id=" + subject + "&max_results=1000"
    )
    rows = complete_list(listing, saturation_limit=1000)
    if any(
        not numeric_id(row.get("subscription_id"))
        or not isinstance(row.get("event_type"), str)
        or not row["event_type"]
        or not isinstance(row.get("filter"), dict)
        or row["filter"].get("user_id") != subject
        for row in rows
    ):
        return _unknown(state)
    matching = [
        row
        for row in rows
        if row.get("event_type") == "post.reply.create"
        and (row.get("filter") or {}).get("user_id") == subject
        and row.get("webhook_id") == state["webhook_id"]
    ]
    saved_subscription_id = state.get("subscription_id")
    if saved_subscription_id:
        anchored = [row for row in rows if row.get("subscription_id") == saved_subscription_id]
        if anchored:
            if (
                len(anchored) != 1
                or len(matching) != 1
                or matching[0].get("subscription_id") != saved_subscription_id
            ):
                return _unknown(state)
        elif matching:
            # A different ID cannot silently replace the last owned receipt.
            return _unknown(state)
    if len(matching) > 1 or any(not numeric_id(row.get("subscription_id")) for row in matching):
        return _unknown(state)
    if not matching:
        state.pop("subscription_id", None)
        state["status"] = "webhook_created"
        return state_response(state, callback_outcome="resumable")
    state["subscription_id"] = matching[0]["subscription_id"]
    filter_ = matching[0]["filter"]
    if set(filter_) - {"user_id", "qualifiers"} or filter_.get("qualifiers", {}) != {}:
        return _unknown(state)
    ready = webhook.get("valid") is True
    state["status"] = "ready" if ready else "not_ready"
    return state_response(state, callback_outcome="configured" if ready else "resumable")
