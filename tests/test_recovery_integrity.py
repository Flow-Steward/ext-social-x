"""Fail-closed remote receipt and account ownership regressions."""

from unittest.mock import Mock

import pytest
from test_manual_setup import URL, setup_invocation

from x_extension.client import XClient, XError
from x_extension.runtime import dispatch


def remote_fixture(self, method, path, **kwargs):
    if path.startswith("/2/webhooks"):
        return {"data": [{"id": "700", "url": URL, "valid": True}], "meta": {"result_count": 1}}
    return {
        "data": [
            {
                "subscription_id": "800",
                "event_type": "post.reply.create",
                "filter": {"user_id": "123"},
                "webhook_id": "700",
            }
        ],
        "meta": {"result_count": 1},
    }


@pytest.mark.parametrize(
    "state",
    [
        {
            "account_user_id": "123",
            "webhook_id": "700",
            "subscription_id": "800",
            "status": "ready",
        },
        {"account_user_id": "123", "status": "unknown"},
    ],
)
def test_status_cannot_reassign_saved_account_to_new_subject(monkeypatch, state):
    call = Mock()

    def request(self, method, path, **kwargs):
        call()
        return remote_fixture(self, method, path, **kwargs)

    monkeypatch.setattr(XClient, "request", request)
    payload = setup_invocation("get_webhook_status", state=state)
    payload["action"]["target"]["connection"]["config"]["oauth"]["subject"] = "456"
    result = dispatch(payload)
    assert result["error_code"] == "invalid_connection"
    call.assert_not_called()


@pytest.mark.parametrize(
    "case",
    ["webhook_errors", "webhook_count", "subscription_errors", "subscription_count", "saturated"],
)
def test_partial_list_envelopes_never_prove_absence_or_resumability(monkeypatch, case):
    def request(self, method, path, **kwargs):
        if path.startswith("/2/webhooks"):
            if case == "webhook_errors":
                return {"data": [], "errors": [{"title": "partial"}]}
            if case == "webhook_count":
                return {"data": [], "meta": {"result_count": 1}}
            return remote_fixture(self, method, path)
        if case == "subscription_errors":
            return {"data": [], "errors": [{"title": "partial"}]}
        if case == "subscription_count":
            return {"data": [], "meta": {"result_count": 1}}
        return {
            "data": [
                {
                    "subscription_id": str(i + 1),
                    "event_type": "post.create",
                    "filter": {"user_id": "123"},
                }
                for i in range(1000)
            ]
        }

    monkeypatch.setattr(XClient, "request", request)
    result = dispatch(setup_invocation("get_webhook_status"))
    assert result.get("result", {}).get("status") not in {
        "ready",
        "not_configured",
        "webhook_created",
    }


@pytest.mark.parametrize(
    "filter_",
    [
        {"user_id": "123", "qualifiers": {"post_id": "111"}},
        {"user_id": "123", "post_id": "111"},
    ],
)
def test_narrowed_subscription_is_not_account_wide_and_retains_owned_id(monkeypatch, filter_):
    def request(self, method, path, **kwargs):
        if path.startswith("/2/webhooks"):
            return remote_fixture(self, method, path)
        return {
            "data": [
                {
                    "subscription_id": "800",
                    "event_type": "post.reply.create",
                    "filter": filter_,
                    "webhook_id": "700",
                }
            ]
        }

    monkeypatch.setattr(XClient, "request", request)
    result = dispatch(setup_invocation("get_webhook_status"))
    assert result["result"]["status"] == "unknown"
    assert result["project_state_updates"][0]["value"]["subscription_id"] == "800"


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"data": {"deleted": False}},
        {"errors": [{"title": "partial"}]},
        {"data": {"deleted": True}, "errors": [{"title": "partial"}]},
    ],
)
def test_delete_requires_authoritative_success_before_dropping_ids(monkeypatch, response):
    monkeypatch.setattr(XClient, "request", Mock(return_value=response))
    result = dispatch(
        setup_invocation(
            "remove_webhook",
            state={"account_user_id": "123", "webhook_id": "700", "subscription_id": "800"},
        )
    )
    assert result["ok"] is True
    assert result["result"]["configured"] is False
    assert result["result"]["error"]["code"] == "timeout_unknown"
    saved = result["project_state_updates"][0]["value"]
    assert saved["webhook_id"] == "700" and saved["subscription_id"] == "800"


def test_confirmed_first_delete_preserves_second_ambiguous_id(monkeypatch):
    def request(self, method, path, **kwargs):
        return (
            {"data": {"deleted": True}}
            if path.startswith("/2/activity/")
            else {"data": {"deleted": False}}
        )

    monkeypatch.setattr(XClient, "request", request)
    result = dispatch(
        setup_invocation(
            "remove_webhook",
            state={"account_user_id": "123", "webhook_id": "700", "subscription_id": "800"},
        )
    )
    saved = result["project_state_updates"][0]["value"]
    assert saved["webhook_id"] == "700" and "subscription_id" not in saved


def test_exact_remote_404_is_confirmed_absence_for_owned_id(monkeypatch):
    monkeypatch.setattr(XClient, "request", Mock(side_effect=XError("not_found", "Not found.")))
    result = dispatch(
        setup_invocation(
            "remove_webhook",
            state={"account_user_id": "123", "webhook_id": "700", "subscription_id": "800"},
        )
    )
    assert result["result"]["status"] == "removed"


@pytest.mark.parametrize("status", [401, 402, 429])
def test_definitive_first_mutation_rejection_can_be_corrected_then_rediscovered(
    monkeypatch, status
):
    import io
    from urllib.error import HTTPError

    transport = Mock(
        side_effect=[
            io.BytesIO(b'{"data":[]}'),
            HTTPError("https://api.x.com/2/webhooks", status, "rejected", {}, None),
            io.BytesIO(b'{"data":[]}'),
            io.BytesIO(b'{"data":{"id":"700","valid":true}}'),
            io.BytesIO(b'{"data":{"subscription":{"subscription_id":"800"}}}'),
        ]
    )
    monkeypatch.setattr("x_extension.client.open_pinned_url", transport)
    result = dispatch(setup_invocation("configure_webhook", callback_url=URL))
    assert result["ok"] is False
    assert result["definitely_no_external_effect"] is True
    assert transport.call_count == 2
    retried = dispatch(setup_invocation("configure_webhook", callback_url=URL))
    assert retried["result"]["configured"] is True
    assert transport.call_count == 5


def test_saved_webhook_id_cannot_be_replaced_by_other_id_with_same_url(monkeypatch):
    def request(self, method, path, **kwargs):
        if path.startswith("/2/webhooks"):
            return {"data": [{"id": "701", "url": URL, "valid": True}]}
        return {"data": []}

    monkeypatch.setattr(XClient, "request", request)
    result = dispatch(
        setup_invocation(
            "get_webhook_status",
            state={"account_user_id": "123", "webhook_id": "700", "subscription_id": "800"},
        )
    )
    assert result["result"]["status"] == "unknown"
    assert result["project_state_updates"][0]["value"]["webhook_id"] == "700"


def test_http_request_timeout_is_ambiguous_not_a_definitive_rejection(monkeypatch):
    import io
    from urllib.error import HTTPError

    monkeypatch.setattr(
        "x_extension.client.open_pinned_url",
        Mock(
            side_effect=[
                io.BytesIO(b'{"data":[]}'),
                HTTPError("https://api.x.com/2/webhooks", 408, "timeout", {}, None),
            ]
        ),
    )
    result = dispatch(setup_invocation("configure_webhook", callback_url=URL))
    assert result["ok"] is True
    assert result["result"]["status"] == "unknown"
    assert result["result"]["configured"] is False
    assert result["result"]["error"]["code"] == "timeout_unknown"


@pytest.mark.parametrize(
    "row",
    [
        {
            "subscription_id": "801",
            "event_type": "post.reply.create",
            "filter": {"user_id": "123"},
            "webhook_id": "700",
        },
        {
            "subscription_id": "800",
            "event_type": "post.create",
            "filter": {"user_id": "123"},
            "webhook_id": "700",
        },
        {
            "subscription_id": "800",
            "event_type": "post.reply.create",
            "filter": {"user_id": "123"},
            "webhook_id": "999",
        },
        {"event_type": "post.create", "filter": {"user_id": "123"}, "webhook_id": "999"},
    ],
)
def test_saved_subscription_anchor_is_never_replaced_or_discarded(monkeypatch, row):
    def request(self, method, path, **kwargs):
        return (
            remote_fixture(self, method, path)
            if path.startswith("/2/webhooks")
            else {"data": [row]}
        )

    monkeypatch.setattr(XClient, "request", request)
    result = dispatch(
        setup_invocation(
            "get_webhook_status",
            state={"account_user_id": "123", "webhook_id": "700", "subscription_id": "800"},
        )
    )
    assert result["result"]["status"] == "unknown"
    assert result["project_state_updates"][0]["value"]["subscription_id"] == "800"


def test_complete_saved_subscription_absence_without_replacement_is_resumable(monkeypatch):
    def request(self, method, path, **kwargs):
        return (
            remote_fixture(self, method, path)
            if path.startswith("/2/webhooks")
            else {"data": [], "meta": {"result_count": 0}}
        )

    monkeypatch.setattr(XClient, "request", request)
    result = dispatch(
        setup_invocation(
            "get_webhook_status",
            state={"account_user_id": "123", "webhook_id": "700", "subscription_id": "800"},
        )
    )
    assert result["result"]["status"] == "webhook_created"
    assert "subscription_id" not in result["project_state_updates"][0]["value"]
