"""Regression cases from the independent extension integration review."""

import json
from unittest.mock import Mock

import pytest
import yaml
from test_lifecycle import invocation

from x_extension import runtime, text
from x_extension.client import XClient, XError


@pytest.mark.parametrize("suffix", ["-other", "?other=article"])
def test_canonical_link_requires_exact_url_token(suffix):
    canonical = "https://example.com/article"
    result = text.validate_post("Read " + canonical + suffix, canonical)
    assert result["text"].endswith("\n" + canonical)


def test_canonical_exact_url_token_with_punctuation_is_not_duplicated():
    canonical = "https://example.com/article"
    value = "Read (" + canonical + ")."
    assert text.validate_post(value, canonical)["text"] == value


def test_action_network_deadline_refuses_new_request_before_io(monkeypatch):
    call = Mock()
    monkeypatch.setattr("x_extension.client.open_pinned_url", call)
    client = XClient("token", deadline=0)
    with pytest.raises(XError) as error:
        client.request("POST", "/2/tweets", body={"text": "hello"})
    assert error.value.unknown is False
    call.assert_not_called()


def test_remaining_budget_caps_request_timeout(monkeypatch):
    monkeypatch.setattr("x_extension.client.monotonic", lambda: 100)
    response = Mock()
    response.read.return_value = json.dumps({"data": {"id": "123"}}).encode()
    manager = Mock()
    manager.__enter__ = Mock(return_value=response)
    manager.__exit__ = Mock(return_value=False)
    call = Mock(return_value=manager)
    monkeypatch.setattr("x_extension.client.open_pinned_url", call)
    XClient("token", deadline=112).request("GET", "/2/users/me")
    assert call.call_args.kwargs["timeout_seconds"] == 12


def test_setup_uses_shared_deadline_without_repeating_host_identity(monkeypatch):
    calls = []

    def request(self, method, path, **kwargs):
        calls.append((path, self.deadline))
        if path == "/2/webhooks":
            return {"data": {"id": "700", "valid": True}}
        if path == "/2/activity/subscriptions":
            return {"data": {"subscription": {"subscription_id": "800"}}}
        raise AssertionError(path)

    monkeypatch.setattr(XClient, "request", request)
    result = runtime.dispatch(
        invocation("configure_webhook", callback_url="https://fs.example/callback/token")
    )
    assert result["ok"], result
    assert len(calls) == 2
    assert len({deadline for _, deadline in calls}) == 1


def test_host_timeout_exceeds_total_network_deadline_with_margin():
    from pathlib import Path

    manifest = yaml.safe_load((Path(__file__).resolve().parents[1] / "extension.yaml").read_text())
    assert manifest["entrypoint"]["timeout_seconds"] >= 120


def test_upload_uses_only_official_json_fields(monkeypatch):
    import io

    from PIL import Image

    source = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(source, "JPEG")
    monkeypatch.setattr(
        runtime, "stream_artifact_bytes", Mock(return_value=iter([source.getvalue()]))
    )
    call = Mock(return_value={"data": {"id": "700", "expires_after_secs": 86400}})
    monkeypatch.setattr(XClient, "request", call)
    result = runtime.dispatch(invocation("upload_media", artifact_handle="artifact:prepared"))
    assert result["ok"]
    assert set(call.call_args.kwargs["body"]) == {"media", "media_category"}


def test_network_timer_restores_alarm_after_timeout_and_exception():
    import signal
    import time

    from x_extension.deadlines import network_timer

    previous_handler = signal.getsignal(signal.SIGALRM)
    with pytest.raises(TimeoutError), network_timer(0.01):
        time.sleep(0.05)
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0
    assert signal.getsignal(signal.SIGALRM) == previous_handler
    with pytest.raises(ValueError), network_timer(1):
        raise ValueError("controlled test error")
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0
    assert signal.getsignal(signal.SIGALRM) == previous_handler
