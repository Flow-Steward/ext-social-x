"""Remote lifecycle recovery and ambiguous paid-write contracts."""

import io
from unittest.mock import Mock

import pytest
from PIL import Image

from x_extension.client import XClient, XError
from x_extension.runtime import dispatch


def invocation(operation, state=None, **inputs):
    target = {
        "connection": {
            "connection_id": "c",
            "config": {"oauth": {"subject": "123", "lifecycle_status": "connected"}},
            "secrets": {"access_token": "user-token"},
        }
    }
    if state is not None:
        target["project_state"] = {
            "items": [
                {
                    "namespace": "x_webhook",
                    "state_key": "registration",
                    "connection_id": "c",
                    "value": state,
                }
            ]
        }
    return {
        "contract_version": "extension_host_v2",
        "mode": "action",
        "runtime_context": {
            "account_id": "a",
            "project_id": "p",
            "group_id": None,
            "for_each_id": None,
            "step_id": None,
            "step_execution_id": None,
            "resources": {"provider_secrets": {"app_bearer_token": "app-token"}},
        },
        "action": {"action_id": operation, "input": inputs, "target": target},
    }


def test_malformed_paid_success_remains_unknown(monkeypatch):
    monkeypatch.setattr(XClient, "request", Mock(return_value={"data": ["unexpected"]}))
    result = dispatch(invocation("publish_post", text="hello"))
    assert result["error_code"] == "timeout_unknown"
    assert result["definitely_no_external_effect"] is False


def test_status_uses_supported_user_filter_and_checks_own_subscription(monkeypatch):
    calls = []

    def request(self, method, path, **kw):
        calls.append(path)
        if path.startswith("/2/webhooks"):
            return {
                "data": [
                    {"id": "999", "valid": True, "url": "https://other.example/callback"},
                    {"id": "700", "valid": True, "url": "https://fs.example/callback/token"},
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
    result = dispatch(
        invocation(
            "get_webhook_status",
            state={"webhook_id": "700", "subscription_id": "800", "account_user_id": "123"},
        )
    )
    assert result["result"]["status"] == "ready"
    assert "/2/activity/subscriptions?user_id=123&max_results=1000" in calls
    assert "/2/webhooks?webhook_config.fields=id,url,valid" in calls


def test_crc_failure_saves_only_own_webhook_and_never_subscribes(monkeypatch):
    calls = []

    def request(self, method, path, **kw):
        calls.append(path)
        if method == "GET" and path.startswith("/2/webhooks?"):
            return {"data": []}
        return (
            {"data": {"id": "123"}}
            if path == "/2/users/me"
            else {"data": {"id": "700", "valid": False}}
        )

    monkeypatch.setattr(XClient, "request", request)
    result = dispatch(
        invocation("configure_webhook", callback_url="https://fs.example/callback/token")
    )
    assert result["result"]["error"]["code"] == "webhook_not_ready"
    assert result["result"]["configured"] is False
    assert result["project_state_updates"][0]["value"]["webhook_id"] == "700"
    assert "/2/activity/subscriptions" not in calls


def test_subscription_failure_saved_and_retry_does_not_create_another_webhook(monkeypatch):
    calls = []

    def request(self, method, path, **kw):
        calls.append((method, path))
        if path == "/2/users/me":
            return {"data": {"id": "123"}}
        if path.startswith("/2/webhooks"):
            row = {"id": "700", "valid": True, "url": "https://fs.example/callback/token"}
            return {"data": [row]} if method == "GET" else {"data": row}
        if method == "GET":
            return {"data": []}
        raise XError("rate_limited", "Please wait.")

    monkeypatch.setattr(XClient, "request", request)
    result = dispatch(
        invocation("configure_webhook", callback_url="https://fs.example/callback/token")
    )
    saved = result["project_state_updates"][0]["value"]
    assert saved["webhook_id"] == "700"
    calls.clear()
    result = dispatch(
        invocation(
            "configure_webhook", state=saved, callback_url="https://fs.example/callback/token"
        )
    )
    assert ("POST", "/2/webhooks") not in calls
    assert ("GET", "/2/webhooks?webhook_config.fields=id,url,valid") in calls


def test_successful_upload_incomplete_metadata_does_not_claim_no_effect(monkeypatch):
    from x_extension import runtime

    source = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(source, "JPEG")
    monkeypatch.setattr(
        runtime, "stream_artifact_bytes", Mock(return_value=iter([source.getvalue()]))
    )

    def request(self, method, path, **kw):
        if path == "/2/media/upload":
            return {"data": {"id": "700", "expires_after_secs": 86400}}
        raise XError("provider_unavailable", "metadata failed")

    monkeypatch.setattr(XClient, "request", request)
    result = dispatch(
        invocation("upload_media", artifact_handle="artifact:prepared", alt_text="A red cover")
    )
    assert result["error_code"] == "timeout_unknown"
    assert result["result"]["media_id"] == "700"
    assert result["definitely_no_external_effect"] is False


def test_partial_removal_preserves_remaining_owned_id(monkeypatch):
    def request(self, method, path, **kw):
        if path.startswith("/2/webhooks"):
            raise XError("provider_unavailable", "try later")
        return {"data": {"deleted": True}}

    monkeypatch.setattr(XClient, "request", request)
    result = dispatch(
        invocation("remove_webhook", state={"webhook_id": "700", "subscription_id": "800"})
    )
    saved = result["project_state_updates"][0]["value"]
    assert saved["webhook_id"] == "700"
    assert "subscription_id" not in saved


def test_reauthorized_account_cannot_reuse_previous_account_state(monkeypatch):
    monkeypatch.setattr(
        XClient, "request", Mock(return_value={"data": {"id": "123", "valid": True}})
    )
    result = dispatch(
        invocation(
            "configure_webhook",
            state={"webhook_id": "700", "subscription_id": "800", "account_user_id": "456"},
            callback_url="https://fs.example/callback/new",
        )
    )
    assert result["error_code"] == "invalid_connection"
    assert result["definitely_no_external_effect"] is True


def test_identity_verification_accepts_pending_target_and_injects_no_secret(monkeypatch):
    request = Mock(return_value={"data": {"id": "123", "username": "owner"}})
    monkeypatch.setattr(XClient, "request", request)
    payload = invocation("verify_identity")
    payload["action"]["target"]["connection"]["config"] = {"oauth": {"lifecycle_status": "pending"}}
    result = dispatch(payload)
    assert result["result"]["subject"] == "123"
    assert result["result"]["health"] == "ok"
    assert "user-token" not in str(result)


def test_malformed_webhook_success_persists_unknown_state(monkeypatch):
    def request(self, method, path, **kw):
        return {"data": []} if method == "GET" else {"data": ["unexpected"]}

    monkeypatch.setattr(XClient, "request", request)
    result = dispatch(
        invocation("configure_webhook", callback_url="https://fs.example/callback/token")
    )
    assert result["result"]["error"]["code"] == "timeout_unknown"
    assert result["result"]["configured"] is False
    assert result["project_state_updates"][0]["value"]["status"] == "unknown"


def test_new_callback_cannot_reuse_old_remote_registration(monkeypatch):
    monkeypatch.setattr(
        XClient, "request", Mock(return_value={"data": {"id": "123", "valid": True}})
    )
    result = dispatch(
        invocation(
            "configure_webhook",
            state={
                "webhook_id": "700",
                "subscription_id": "800",
                "account_user_id": "123",
                "callback_url_hash": "old-hash",
            },
            callback_url="https://fs.example/callback/new",
        )
    )
    assert result["error_code"] == "webhook_not_ready"
    assert result["definitely_no_external_effect"] is True


def test_unknown_registration_without_saved_id_requires_reconciliation(monkeypatch):
    call = Mock()
    monkeypatch.setattr(XClient, "request", call)
    result = dispatch(
        invocation("remove_webhook", state={"status": "unknown", "account_user_id": "123"})
    )
    assert result["error_code"] == "timeout_unknown"
    assert result["definitely_no_external_effect"] is False
    call.assert_not_called()


@pytest.mark.parametrize(
    "data",
    [
        {"id": "700", "valid": True, "url": "https://fs.example/callback/token"},
        [],
        [None],
        [{"id": "999", "valid": True, "url": "https://other.example/callback"}],
        [{"id": "700", "valid": "true"}],
    ],
)
def test_status_does_not_adopt_missing_foreign_or_malformed_webhook(monkeypatch, data):
    def request(self, method, path, **kw):
        if path.startswith("/2/webhooks"):
            return {"data": data}
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
    result = dispatch(
        invocation(
            "get_webhook_status",
            state={"webhook_id": "700", "subscription_id": "800", "account_user_id": "123"},
        )
    )
    assert result.get("result", {}).get("status") != "ready"
