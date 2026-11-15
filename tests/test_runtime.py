"""Provider boundary and deterministic normalization regression tests."""

import io
from unittest.mock import Mock

import pytest
from PIL import Image

from x_extension import images, runtime, text
from x_extension.client import XClient, XError


def envelope(operation="validate_post", **inputs):
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
        },
        "action": {
            "action_id": operation,
            "input": inputs,
            "target": {
                "connection": {
                    "connection_id": "c",
                    "secrets": {"access_token": "user-token"},
                    "config": {"oauth": {"subject": "123", "lifecycle_status": "connected"}},
                }
            },
        },
    }


@pytest.mark.parametrize(
    ("value", "length"),
    [
        ("abc", 3),
        ("漢字", 4),
        ("cafe\u0301", 4),
        ("👨‍👩‍👧‍👦", 2),
        ("👋🏽", 2),
        ("🇱🇹", 2),
        ("See https://example.com/a/really/long/link", 27),
        ("example.com", 23),
    ],
)
def test_weighted_unicode_and_urls(value, length):
    assert text.validate_post(value)["weighted_length"] == length


def test_link_preserved_and_not_truncated():
    value = text.validate_post("x" * 260, "https://example.com/full-article")
    assert value["text"].endswith("https://example.com/full-article")
    assert value["valid"] is False
    assert value["weighted_length"] == 284


def test_invalid_envelope_before_any_io(monkeypatch):
    call = Mock(side_effect=AssertionError("no I/O"))
    monkeypatch.setattr(runtime, "XClient", call)
    result = runtime.dispatch({"mode": "action"})
    assert result["error_code"] == "invalid_host_envelope"
    assert result["definitely_no_external_effect"] is True
    call.assert_not_called()


def test_one_context_validation(monkeypatch):
    validate = Mock(wraps=runtime.runtime_context_from_payload)
    monkeypatch.setattr(runtime, "runtime_context_from_payload", validate)
    assert runtime.dispatch(envelope(text="hello"))["ok"]
    validate.assert_called_once()


def test_prepare_static_jpeg_without_crop():
    source = io.BytesIO()
    Image.new("RGBA", (300, 300), (255, 0, 0, 128)).save(source, "PNG")
    data = images.prepare_image(source.getvalue())
    image = Image.open(io.BytesIO(data))
    assert image.format == "JPEG"
    assert image.size == (1200, 675)
    assert len(data) <= 5_000_000
    assert image.getpixel((0, 0)) == (255, 255, 255)
    assert not image.getexif()


def test_reject_animated_image():
    source = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(
        source,
        "GIF",
        save_all=True,
        append_images=[Image.new("RGB", (10, 10), "blue")],
        duration=100,
        loop=0,
    )
    with pytest.raises(XError, match="static"):
        images.prepare_image(source.getvalue())


def test_image_byte_limit():
    with pytest.raises(XError):
        images.prepare_image(b"0" * (20 * 1024 * 1024 + 1))


def reply_event():
    return {
        "data": {
            "event_type": "post.reply.create",
            "event_uuid": "delivery-1",
            "created_at": "2026-11-14T12:00:00Z",
            "filter": {"user_id": "123"},
            "payload": {
                "id": "999",
                "text": "What about this?",
                "author_id": "456",
                "in_reply_to_tweet_id": "111",
                "in_reply_to_user_id": "123",
                "conversation_id": "100",
            },
        }
    }


def event_envelope(event):
    payload = envelope(
        "receive_event",
        callback={
            "callback_id": "events",
            "authenticated": True,
            "connection_id": "c",
            "project_id": "p",
        },
        request={
            "method": "POST",
            "json": event,
            "provider": {
                "provider_key": "flowsteward.x",
                "connection_id": "c",
                "project_id": "p",
                "binding_config": {"oauth": {"subject": "123", "lifecycle_status": "connected"}},
            },
        },
    )
    payload["action"]["target"] = {}
    payload["host"] = {
        "principal": {"actor_id": "flowsteward.x_callback", "principal_type": "system_actor"},
        "scope": {"project_id": "p", "account_id": "a"},
    }
    return payload


def test_account_wide_external_old_post_normalized_stably():
    event = reply_event()
    first = runtime.dispatch(event_envelope(event))
    assert first["ok"]
    event["data"]["event_uuid"] = "fresh-delivery"
    second = runtime.dispatch(event_envelope(event))
    one, two = first["events"][0], second["events"][0]
    assert one["correlation_id"] == two["correlation_id"]
    assert one["event_type"] == "x.comment.received"
    assert one["payload"]["connection_id"] == "c"
    assert one["payload"]["parent_post_id"] == "111"
    assert one["payload"]["conversation_id"] == "100"
    assert one["payload"]["comment_id"] == "999"


@pytest.mark.parametrize("change", ["self", "foreign", "deep", "unsigned", "missing"])
def test_no_self_foreign_deep_or_unsigned_events(change):
    event = reply_event()
    payload = event_envelope(event)
    if change == "self":
        event["data"]["payload"]["author_id"] = "123"
    if change == "foreign":
        event["data"]["filter"]["user_id"] = "987"
    if change == "deep":
        event["data"]["payload"]["in_reply_to_user_id"] = "888"
    if change == "unsigned":
        payload["action"]["input"]["callback"]["authenticated"] = False
    if change == "missing":
        del event["data"]["payload"]["id"]
    assert not runtime.dispatch(payload).get("events")


def test_prepare_uses_sdk_artifact_grants(monkeypatch):
    source = io.BytesIO()
    Image.new("RGB", (16, 9), "red").save(source, "PNG")
    read = Mock(return_value=iter([source.getvalue()]))
    write = Mock(return_value={"artifact_handle": "artifact:prepared"})
    monkeypatch.setattr(runtime, "stream_artifact_bytes", read)
    monkeypatch.setattr(runtime, "write_artifact_bytes", write)
    result = runtime.dispatch(envelope("prepare_image", artifact_handle="artifact:source"))
    assert result["result"]["image_artifact_handle"] == "artifact:prepared"
    assert read.call_args.kwargs["binding_key"] == "source_image"
    assert write.call_args.kwargs["binding_key"] == "image_artifact_handle"


def test_publish_long_text_rejected_before_paid_call(monkeypatch):
    client = Mock()
    monkeypatch.setattr(runtime, "XClient", client)
    result = runtime.dispatch(envelope("publish_post", text="漢" * 141))
    assert result["error_code"] == "invalid_post"
    client.return_value.request.assert_not_called()


def test_publish_and_reply_official_payload(monkeypatch):
    calls = []

    def request(self, method, path, **kw):
        calls.append((method, path, kw))
        return {"data": {"id": "777", "text": "Hello"}}

    monkeypatch.setattr(XClient, "request", request)
    result = runtime.dispatch(
        envelope("reply_to_post", reply_to_post_id="999", text="Hello", media_ids=["222"])
    )
    assert result["result"]["post_id"] == "777"
    assert calls[0][2]["body"] == {
        "text": "Hello",
        "reply": {"in_reply_to_tweet_id": "999"},
        "media": {"media_ids": ["222"]},
    }
    assert result["external_effect_status"] == "succeeded"


def test_timeout_mutation_unknown_and_no_retry(monkeypatch):
    transport = Mock(side_effect=TimeoutError("secret user-token must not appear"))
    monkeypatch.setattr("x_extension.client.open_pinned_url", transport)
    with pytest.raises(XError) as error:
        XClient("user-token").request("POST", "/2/tweets", body={"text": "x"})
    assert error.value.unknown
    assert "user-token" not in str(error.value)
    assert transport.call_count == 1


def test_webhook_and_private_subscription_auth_split(monkeypatch):
    calls = []

    def request(self, method, path, **kw):
        calls.append((self.token, method, path, kw))
        if path == "/2/users/me":
            return {"data": {"id": "123", "username": "owner"}}
        if path.startswith("/2/webhooks?"):
            return {"data": []}
        if path == "/2/webhooks":
            return {"data": {"id": "700", "valid": True}}
        return {"data": {"subscription": {"subscription_id": "800"}}}

    monkeypatch.setattr(XClient, "request", request)
    payload = envelope("configure_webhook", callback_url="https://fs.example/webhook/token")
    payload["runtime_context"]["resources"] = {
        "provider_secrets": {"app_bearer_token": "app-token"}
    }
    result = runtime.dispatch(payload)
    assert result["ok"], result
    create = next(x for x in calls if x[2] == "/2/activity/subscriptions")
    assert create[0] == "user-token"
    assert create[3]["body"] == {
        "event_type": "post.reply.create",
        "filter": {"user_id": "123"},
        "webhook_id": "700",
    }
    assert next(x for x in calls if x[2] == "/2/webhooks")[0] == "app-token"
    assert "post_id" not in str(create[3])


def test_health_is_local_only():
    from health import health_result

    assert health_result()["ok"] is True


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "authorization_required"),
        (403, "forbidden"),
        (402, "credits_required"),
        (404, "not_found"),
        (429, "rate_limited"),
        (503, "provider_unavailable"),
    ],
)
def test_http_errors_are_safe_and_read_retry_hint(monkeypatch, status, code):
    from urllib.error import HTTPError

    error = HTTPError(
        "https://api.x.com/2/tweets",
        status,
        "provider secret-token",
        {"Retry-After": "30"},
        io.BytesIO(b"secret-token"),
    )
    monkeypatch.setattr("x_extension.client.open_pinned_url", Mock(side_effect=error))
    with pytest.raises(XError) as failure:
        XClient("secret-token").request("GET", "/2/tweets/123")
    assert failure.value.code == code
    assert "secret-token" not in str(failure.value)
    if status == 429:
        assert failure.value.retry_after == 30


def test_server_error_after_mutation_is_unknown(monkeypatch):
    from urllib.error import HTTPError

    monkeypatch.setattr(
        "x_extension.client.open_pinned_url",
        Mock(side_effect=HTTPError("https://api.x.com", 503, "unavailable", {}, None)),
    )
    with pytest.raises(XError) as failure:
        XClient("token").request("POST", "/2/tweets", body={"text": "hello"})
    assert failure.value.unknown


def test_automatic_reply_requires_all_attestations(monkeypatch):
    send = Mock()
    monkeypatch.setattr(XClient, "request", send)
    result = runtime.dispatch(
        envelope("reply_to_post", reply_to_post_id="999", text="Hello", automated=True)
    )
    assert result["error_code"] == "forbidden"
    assert result["definitely_no_external_effect"]
    send.assert_not_called()


def test_media_invalid_bytes_rejected_before_network(monkeypatch):
    send = Mock()
    monkeypatch.setattr(XClient, "request", send)
    monkeypatch.setattr(
        runtime, "stream_artifact_bytes", Mock(return_value=iter([b"not an image"]))
    )
    result = runtime.dispatch(envelope("upload_media", artifact_handle="artifact:raw"))
    assert not result["ok"]
    send.assert_not_called()


def test_private_identity_comes_only_from_host_config(monkeypatch):
    payload = event_envelope(reply_event())
    payload["action"]["input"]["request"]["provider"]["binding_config"] = {}
    payload["action"]["input"]["account_user_id"] = "123"
    assert not runtime.dispatch(payload)["ok"]


def test_event_payload_stable_across_delivery_time_and_uuid():
    event = reply_event()
    first = runtime.dispatch(event_envelope(event))
    event["data"].update(event_uuid="retry", created_at="2027-01-01T00:00:00Z")
    second = runtime.dispatch(event_envelope(event))
    assert first["events"][0]["payload"] == second["events"][0]["payload"]
    assert first["events"][0]["metadata"]["event_uuid"] == "delivery-1"


def test_remove_only_saved_owned_remote_ids(monkeypatch):
    call = Mock()
    monkeypatch.setattr(XClient, "request", call)
    result = runtime.dispatch(envelope("remove_webhook", webhook_id="foreign"))
    assert result["ok"]
    call.assert_not_called()


@pytest.mark.parametrize(
    "principal",
    [
        {"actor_id": "operator", "actor_type": "user"},
        {"actor_id": "service", "actor_type": "service_account"},
        {"actor_id": None},
        {"actor_type": ""},
    ],
)
def test_raw_invoke_forged_callback_host_rejected_by_trusted_runtime_audit(principal):
    payload = event_envelope(reply_event())
    payload["runtime_context"].update(principal)
    result = runtime.dispatch(payload)
    assert result["ok"] is False
    assert not result.get("events")


def test_callback_ordinary_action_principal_cannot_forge_authenticated_input():
    payload = event_envelope(reply_event())
    payload["host"]["principal"] = {"actor_id": "operator", "principal_type": "user"}
    assert runtime.dispatch(payload)["ok"] is False


def test_comment_source_separates_connections_and_projects():
    payload = event_envelope(reply_event())
    first = runtime.dispatch(payload)["events"][0]["correlation_id"]
    payload["action"]["input"]["callback"]["connection_id"] = "other"
    payload["action"]["input"]["request"]["provider"]["connection_id"] = "other"
    second = runtime.dispatch(payload)["events"][0]["correlation_id"]
    assert second != first
    payload["action"]["input"]["callback"]["project_id"] = "other-project"
    payload["action"]["input"]["request"]["provider"]["project_id"] = "other-project"
    payload["host"]["scope"]["project_id"] = "other-project"
    payload["runtime_context"]["project_id"] = "other-project"
    assert runtime.dispatch(payload)["events"][0]["correlation_id"] not in {first, second}


def test_declared_query_reads_params_envelope():
    payload = envelope()
    target = payload.pop("action")["target"]
    payload.update(mode="query", query={"query_id": "provider_health", "params": {}}, target=target)
    assert runtime.dispatch(payload)["result"]["status"] == "bundle_ready"
    payload["query"]["params"] = "malformed"
    assert runtime.dispatch(payload)["error_code"] == "invalid_payload"
