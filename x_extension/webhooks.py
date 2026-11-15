"""Provider-owned webhook lifecycle; durable state belongs exclusively to Core."""

from __future__ import annotations

import hashlib
from urllib.parse import urlsplit

from .client import XClient, XError
from .events import numeric_id, verified_subject
from .remote_receipts import confirmed_deletion
from .webhook_state import state_from_target as state_from_target
from .webhook_state import state_response
from .webhook_status import owned_webhook
from .webhook_status import status as status


def app_token(payload: dict, connection: dict) -> str:
    resources = (payload.get("runtime_context") or {}).get("resources") or {}
    return str((resources.get("provider_secrets") or {}).get("app_bearer_token") or "")


def configure(options: dict, connection: dict, state: dict, user: XClient, app: XClient) -> dict:
    subject = verified_subject(connection)
    url = options.get("callback_url")
    if (
        not isinstance(url, str)
        or len(url) > 200
        or urlsplit(url).scheme != "https"
        or not urlsplit(url).hostname
    ):
        raise XError(
            "invalid_payload",
            "A Core-issued public HTTPS callback URL of at most 200 characters is required.",
        )
    has_remote = bool(state.get("webhook_id") or state.get("subscription_id"))
    if has_remote and state.get("account_user_id") != subject:
        raise XError(
            "invalid_connection",
            "Saved webhook belongs to a previous OAuth account; reconcile and remove it before setup.",
        )
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    if has_remote and state.get("callback_url_hash") and state["callback_url_hash"] != url_hash:
        raise XError(
            "webhook_not_ready",
            "Callback registration changed; remove the saved remote webhook before reconfiguring.",
        )
    if state.get("status") == "unknown":
        raise XError(
            "timeout_unknown",
            "Previous webhook setup outcome is unknown; reconcile X state before setup.",
            unknown=True,
        )
    state.update(account_user_id=subject, callback_url_hash=url_hash)
    effect_possible = False
    try:
        if not state.get("webhook_id"):
            remote = app.request("POST", "/2/webhooks", body={"url": url}).get("data") or {}
            effect_possible = True
            if not isinstance(remote, dict):
                raise XError(
                    "timeout_unknown",
                    "X webhook returned malformed data; reconcile before retry.",
                    unknown=True,
                )
            state.update(
                webhook_id=numeric_id(remote.get("id")),
                account_user_id=subject,
                status="webhook_created",
            )
            if not state["webhook_id"]:
                raise XError(
                    "timeout_unknown",
                    "X webhook creation returned no stable ID; reconcile before retry.",
                    unknown=True,
                )
            if remote.get("valid") is not True:
                raise XError(
                    "webhook_not_ready",
                    "X did not validate CRC; verify the same app's OAuth client secret and HTTPS access.",
                )
        else:
            remote = owned_webhook(app, state)
            if remote.get("valid") is not True:
                raise XError(
                    "webhook_not_ready",
                    "Saved X webhook is not CRC validated; check matching app credentials.",
                )
        if not state.get("subscription_id"):
            data = (
                user.request(
                    "POST",
                    "/2/activity/subscriptions",
                    body={
                        "event_type": "post.reply.create",
                        "filter": {"user_id": subject},
                        "webhook_id": state["webhook_id"],
                    },
                ).get("data")
                or {}
            )
            effect_possible = True
            if not isinstance(data, dict):
                raise XError(
                    "timeout_unknown",
                    "X subscription returned malformed data; reconcile before retry.",
                    unknown=True,
                )
            subscription = data.get("subscription") or data
            if not isinstance(subscription, dict):
                raise XError(
                    "timeout_unknown",
                    "X subscription returned malformed data; reconcile before retry.",
                    unknown=True,
                )
            state["subscription_id"] = numeric_id(subscription.get("subscription_id"))
            if not state["subscription_id"]:
                raise XError(
                    "timeout_unknown",
                    "X subscription creation returned no stable ID; reconcile before retry.",
                    unknown=True,
                )
        state["status"] = "ready"
        return state_response(state, callback_outcome="configured")
    except XError as exc:
        exc.effect_possible = exc.effect_possible or effect_possible
        state["status"] = "unknown" if exc.unknown else "setup_failed"
        exc.details["project_state_updates"] = state_response(state)["project_state_updates"]
        raise


def remove(state: dict, user: XClient, app: XClient) -> dict:
    effect_possible = False
    if state.get("status") == "unknown":
        raise XError(
            "timeout_unknown",
            "Unknown remote registration must be reconciled before removal or replacement.",
            unknown=True,
        )
    try:
        for field, client, path in [
            ("subscription_id", user, "/2/activity/subscriptions/"),
            ("webhook_id", app, "/2/webhooks/"),
        ]:
            id_ = numeric_id(state.get(field))
            if id_:
                try:
                    deletion = client.request("DELETE", path + id_)
                    effect_possible = True
                    if not confirmed_deletion(deletion):
                        raise XError(
                            "timeout_unknown",
                            "X did not confirm removal; retain the owned ID and reconcile before retry.",
                            unknown=True,
                            effect_possible=True,
                        )
                except XError as exc:
                    if exc.code != "not_found":
                        raise
                effect_possible = True
                state.pop(field, None)
        state["status"] = "removed"
        return state_response(state, callback_outcome="absent")
    except XError as exc:
        exc.effect_possible = exc.effect_possible or effect_possible
        state["status"] = "remove_failed"
        exc.details["project_state_updates"] = state_response(state)["project_state_updates"]
        raise
