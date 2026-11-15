"""SDK callback setup intent and exact remote reconciliation receipts."""

import hashlib
from unittest.mock import Mock

from test_lifecycle import invocation

from x_extension.client import XClient
from x_extension.runtime import dispatch

URL = "https://fs.example/callback/token"
URL_HASH = hashlib.sha256(URL.encode()).hexdigest()


def setup_invocation(operation, state=None, **inputs):
    payload = invocation(operation, state=state, **inputs)
    payload["runtime_context"]["source"] = "extension_callback_registration"
    payload["action"]["target"]["callback_setup"] = {
        "outcome": "fresh",
        "attempt_id": "attempt",
        "callback_url_hash": URL_HASH,
    }
    return payload


def test_configure_success_returns_configured_receipt(monkeypatch):
    def request(self, method, path, **kw):
        if path == "/2/users/me":
            return {"data": {"id": "123"}}
        if path == "/2/webhooks":
            return {"data": {"id": "700", "valid": True}}
        return {"data": {"subscription": {"subscription_id": "800"}}}

    monkeypatch.setattr(XClient, "request", request)
    result = dispatch(setup_invocation("configure_webhook", callback_url=URL))
    assert result["result"]["callback_setup"]["outcome"] == "configured"


def test_missing_host_setup_target_cannot_start_remote_registration(monkeypatch):
    call = Mock()
    monkeypatch.setattr(XClient, "request", call)
    payload = invocation("configure_webhook", callback_url=URL)
    payload["action"]["target"].pop("callback_setup", None)
    result = dispatch(payload)
    assert not result["ok"]
    call.assert_not_called()


def test_status_reconciles_exact_owned_webhook_without_saved_ids(monkeypatch):
    def request(self, method, path, **kw):
        if path.startswith("/2/webhooks"):
            return {
                "data": [
                    {"id": "999", "url": "https://other.example/callback", "valid": True},
                    {"id": "700", "url": URL, "valid": True},
                ]
            }
        return {
            "data": [
                {
                    "subscription_id": "800",
                    "event_type": "post.reply.create",
                    "filter": {"user_id": "123"},
                    "webhook_id": "700",
                }
            ]
        }

    monkeypatch.setattr(XClient, "request", request)
    payload = setup_invocation("get_webhook_status")
    payload["action"]["target"]["callback_setup"]["outcome"] = "unknown"
    result = dispatch(payload)
    assert result["result"]["callback_setup"]["outcome"] == "configured"
    saved = result["project_state_updates"][0]["value"]
    assert saved["webhook_id"] == "700"
    assert saved["subscription_id"] == "800"


def test_owned_webhook_without_subscription_is_resumable(monkeypatch):
    def request(self, method, path, **kw):
        return (
            {"data": [{"id": "700", "url": URL, "valid": True}]}
            if path.startswith("/2/webhooks")
            else {"data": []}
        )

    monkeypatch.setattr(XClient, "request", request)
    result = dispatch(setup_invocation("get_webhook_status"))
    assert result["result"]["callback_setup"]["outcome"] == "resumable"
    assert result["project_state_updates"][0]["value"]["webhook_id"] == "700"


def test_status_absence_requires_complete_exact_url_query(monkeypatch):
    monkeypatch.setattr(
        XClient,
        "request",
        Mock(
            return_value={
                "data": [{"id": "999", "url": "https://other.example/callback", "valid": True}]
            }
        ),
    )
    result = dispatch(setup_invocation("get_webhook_status"))
    assert result["result"]["callback_setup"]["outcome"] == "absent"


def test_duplicate_exact_callback_urls_stay_unknown(monkeypatch):
    monkeypatch.setattr(
        XClient,
        "request",
        Mock(
            return_value={
                "data": [
                    {"id": "700", "url": URL, "valid": True},
                    {"id": "701", "url": URL, "valid": True},
                ]
            }
        ),
    )
    result = dispatch(setup_invocation("get_webhook_status"))
    assert result["result"]["callback_setup"]["outcome"] == "unknown"


def test_missing_app_secret_is_safe_not_started_receipt(monkeypatch):
    call = Mock()
    monkeypatch.setattr(XClient, "request", call)
    payload = setup_invocation("configure_webhook", callback_url=URL)
    payload["runtime_context"]["resources"] = {}
    result = dispatch(payload)
    assert result["ok"] is False
    assert result["result"]["callback_setup"]["outcome"] == "not_started"
    call.assert_not_called()


def test_local_url_validation_is_safe_not_started_receipt(monkeypatch):
    call = Mock()
    monkeypatch.setattr(XClient, "request", call)
    result = dispatch(
        setup_invocation("configure_webhook", callback_url="http://invalid.example/callback")
    )
    assert result["result"]["callback_setup"]["outcome"] == "not_started"
    call.assert_not_called()


def test_error_after_created_webhook_never_claims_not_started(monkeypatch):
    from x_extension.client import XError

    def request(self, method, path, **kwargs):
        if path == "/2/webhooks":
            return {"data": {"id": "700", "valid": True}}
        raise XError("rate_limited", "Please wait.")

    monkeypatch.setattr(XClient, "request", request)
    result = dispatch(setup_invocation("configure_webhook", callback_url=URL))
    assert result["ok"] is False
    assert result["result"].get("callback_setup", {}).get("outcome") != "not_started"
    assert result["project_state_updates"][0]["value"]["webhook_id"] == "700"
