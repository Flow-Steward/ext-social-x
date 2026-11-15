"""Ordinary action setup and exact remote reconciliation; no host intent protocol."""

import hashlib
from unittest.mock import Mock

from test_lifecycle import invocation

from x_extension.client import XClient, XError
from x_extension.runtime import dispatch

URL = "https://fs.example/callback/token"
URL_HASH = hashlib.sha256(URL.encode()).hexdigest()


def setup_invocation(operation, state=None, **inputs):
    if operation == "get_webhook_status":
        inputs.setdefault("callback_url", URL)
    return invocation(operation, state=state, **inputs)


def test_fresh_setup_lists_before_creating_without_host_marker(monkeypatch):
    calls = []

    def request(self, method, path, **kw):
        calls.append((method, path))
        if method == "GET":
            return {"data": []}
        if path == "/2/webhooks":
            return {"data": {"id": "700", "valid": True}}
        return {"data": {"subscription": {"subscription_id": "800"}}}

    monkeypatch.setattr(XClient, "request", request)
    result = dispatch(setup_invocation("configure_webhook", callback_url=URL))
    assert result["result"]["configured"] is True
    assert calls[0] == ("GET", "/2/webhooks?webhook_config.fields=id,url,valid")
    assert "callback_setup" not in result["result"]


def test_configure_rediscovers_exact_url_and_subscription_after_lost_state(monkeypatch):
    calls = []

    def request(self, method, path, **kw):
        calls.append(method)
        if path.startswith("/2/webhooks"):
            return {"data": [{"id": "700", "url": URL, "valid": True}]}
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
    result = dispatch(setup_invocation("configure_webhook", callback_url=URL))
    assert result["result"]["configured"] is True
    assert result["project_state_updates"][0]["value"]["subscription_id"] == "800"
    assert calls == ["GET", "GET"]


def test_owned_webhook_without_subscription_is_explicitly_resumable(monkeypatch):
    monkeypatch.setattr(
        XClient,
        "request",
        lambda self, method, path, **kw: (
            {"data": [{"id": "700", "url": URL, "valid": True}]}
            if path.startswith("/2/webhooks")
            else {"data": []}
        ),
    )
    result = dispatch(setup_invocation("get_webhook_status"))
    assert result["result"]["status"] == "webhook_created"
    assert result["result"]["configured"] is False
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
    assert result["result"]["status"] == "not_configured"
    assert result["result"]["configured"] is False


def test_duplicate_exact_callback_urls_stay_unknown_and_never_create(monkeypatch):
    call = Mock(
        return_value={
            "data": [
                {"id": "700", "url": URL, "valid": True},
                {"id": "701", "url": URL, "valid": True},
            ]
        }
    )
    monkeypatch.setattr(XClient, "request", call)
    result = dispatch(setup_invocation("configure_webhook", callback_url=URL))
    assert result["result"]["status"] == "unknown"
    assert result["result"]["reconciliation_required"] is True
    assert call.call_args.args[0] == "GET"


def test_missing_app_bearer_and_invalid_url_are_local_failures(monkeypatch):
    call = Mock()
    monkeypatch.setattr(XClient, "request", call)
    payload = setup_invocation("configure_webhook", callback_url=URL)
    payload["runtime_context"]["resources"] = {}
    assert dispatch(payload)["ok"] is False
    assert (
        dispatch(
            setup_invocation("configure_webhook", callback_url="http://invalid.example/callback")
        )["ok"]
        is False
    )
    call.assert_not_called()


def test_partial_remote_setup_is_processed_record_not_configured_success(monkeypatch):
    def request(self, method, path, **kw):
        if method == "GET":
            return {"data": []}
        if path == "/2/webhooks":
            return {"data": {"id": "700", "valid": True}}
        raise XError("rate_limited", "Please wait.")

    monkeypatch.setattr(XClient, "request", request)
    result = dispatch(setup_invocation("configure_webhook", callback_url=URL))
    assert result["ok"] is True
    assert result["result"]["configured"] is False
    assert result["result"]["status"] == "setup_failed"
    assert result["result"]["error"]["code"] == "rate_limited"
    assert result["result"]["reconciliation_required"] is True
    assert result["project_state_updates"][0]["value"]["webhook_id"] == "700"


def test_existing_crc_invalid_webhook_without_subscription_never_posts(monkeypatch):
    calls = []

    def request(self, method, path, **kw):
        calls.append((method, path))
        if path.startswith("/2/webhooks?"):
            return {
                "data": [{"id": "700", "url": URL, "valid": False}],
                "meta": {"result_count": 1},
            }
        if path.startswith("/2/activity/subscriptions?"):
            return {"data": [], "meta": {"result_count": 0}}
        raise AssertionError("CRC-invalid webhook must not cause a mutation")

    monkeypatch.setattr(XClient, "request", request)
    result = dispatch(setup_invocation("configure_webhook", callback_url=URL))
    assert result["ok"] is True
    assert result["result"]["status"] == "not_ready"
    assert result["result"]["configured"] is False
    assert result["result"]["reconciliation_required"] is True
    saved = result["project_state_updates"][0]["value"]
    assert saved["status"] == "not_ready"
    assert saved["webhook_id"] == "700"
    assert "subscription_id" not in saved
    assert all(method == "GET" for method, _ in calls)
