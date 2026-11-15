"""One validated SDK entry boundary for all provider and artifact operations."""

from __future__ import annotations

import base64
from time import monotonic
from typing import Any

from flowsteward_extension_sdk import runtime_context_from_payload
from flowsteward_extension_sdk.artifacts import (
    ArtifactAccessError,
    stream_artifact_bytes,
    write_artifact_bytes,
)

from . import images, text, webhooks
from .client import XClient, XError
from .errors import failure as failure
from .events import numeric_id, receive_event, verified_subject

MUTATIONS = {"publish_post", "reply_to_post", "upload_media"}


def dispatch(payload: dict) -> dict:
    id_ = ""
    deadline = monotonic() + 75
    try:
        runtime_context_from_payload(payload)
    except ValueError as exc:
        return failure("invalid_host_envelope", str(exc))
    try:
        operation = (
            payload.get("action") if payload.get("mode") == "action" else payload.get("query")
        )
        if not isinstance(operation, dict):
            raise XError("invalid_payload", "An action or query object is required.")
        id_ = str(operation.get("action_id") or operation.get("query_id") or "")
        options = operation.get("input" if payload.get("mode") == "action" else "params") or {}
        if not isinstance(options, dict):
            raise XError("invalid_payload", "Operation input must be an object.")
        target = (
            operation.get("target") if payload.get("mode") == "action" else payload.get("target")
        ) or {}
        connection = target.get("connection") or {}
        if id_ == "provider_health":
            return {"ok": True, "result": {"status": "bundle_ready"}}
        if id_ == "validate_post":
            return {
                "ok": True,
                "result": text.validate_post(options.get("text"), options.get("canonical_url")),
            }
        if id_ == "prepare_image":
            body = images.prepare_image(_artifact(payload, options))
            result = write_artifact_bytes(
                payload,
                body,
                binding_key="image_artifact_handle",
                content_type="image/jpeg",
                timeout_seconds=10,
            )
            return {
                "ok": True,
                "result": {
                    "image_artifact_handle": result["artifact_handle"],
                    "mime_type": "image/jpeg",
                    "width": 1200,
                    "height": 675,
                    "size_bytes": len(body),
                },
            }
        if id_ == "receive_event":
            return receive_event(
                options, payload.get("host") or {}, payload.get("runtime_context") or {}
            )
        if id_ in {"publish_post", "reply_to_post"}:
            return _publish(id_, options, connection, deadline)
        if id_ == "upload_media":
            return _upload(payload, options, connection, deadline)
        user = XClient(
            str((connection.get("secrets") or {}).get("access_token") or ""), deadline=deadline
        )
        if id_ == "verify_identity":
            data = user.request("GET", "/2/users/me").get("data") or {}
            subject = _id(data.get("id"))
            return {
                "ok": True,
                "result": {
                    "subject": subject,
                    "verified_display_name": data.get("username") or subject,
                    "safe_metadata": {},
                    "health": "ok",
                },
            }
        if id_ == "get_post":
            id_value = _id(options.get("post_id"))
            data = user.request(
                "GET",
                "/2/tweets/"
                + id_value
                + "?tweet.fields=author_id,conversation_id,created_at,referenced_tweets,entities",
            ).get("data")
            if not isinstance(data, dict) or data.get("id") != id_value:
                raise XError("not_found", "X post is unavailable to this connection.")
            refs = data.get("referenced_tweets") or []
            parent = next((r.get("id") for r in refs if r.get("type") == "replied_to"), None)
            return {
                "ok": True,
                "result": {
                    "post": {
                        **data,
                        "parent_post_id": parent,
                        "url": "https://x.com/i/web/status/" + id_value,
                    }
                },
            }
        if id_ in {"configure_webhook", "get_webhook_status", "remove_webhook"}:
            subject = verified_subject(connection)
            if not connection.get("connection_id"):
                raise XError(
                    "invalid_connection", "Select an exact X connection for webhook management."
                )
            state = webhooks.state_from_target(target, connection["connection_id"])
            if state.get("account_user_id") and state["account_user_id"] != subject:
                raise XError(
                    "invalid_connection", "Saved remote state belongs to a previous OAuth account."
                )
            if id_ == "remove_webhook" and not state:
                return webhooks.state_response({"status": "removed"})
            app = XClient(webhooks.app_token(payload, connection), deadline=deadline)
            if id_ == "configure_webhook":
                return webhooks.configure(options, connection, state, user, app)
            if id_ == "get_webhook_status":
                return webhooks.status(state, user, app, options, subject)
            return webhooks.remove(state, user, app)
        raise XError("invalid_payload", "Unknown X operation.")
    except XError as exc:
        return failure(
            exc.code,
            str(exc),
            unknown=exc.unknown,
            **({"retry_after_seconds": exc.retry_after} if exc.retry_after else {}),
            **exc.details,
        )
    except ArtifactAccessError:
        return failure("artifact_access_failed", "Cannot access the host-granted image artifact.")
    except (ValueError, TypeError, KeyError, AttributeError, OSError):
        return failure(
            "internal_error", "X operation failed before a confirmed result; check configuration."
        )


def _artifact(payload: dict, options: dict) -> bytes:
    handle = options.get("artifact_handle")
    if not isinstance(handle, str) or not handle.startswith("artifact:"):
        raise XError("invalid_payload", "A project-scoped artifact handle is required.")
    data = bytearray()
    for chunk in stream_artifact_bytes(
        payload, artifact_id=handle, binding_key="source_image", timeout_seconds=10
    ):
        if len(data) + len(chunk) > images.INPUT_MAX_BYTES:
            raise XError("input_too_large", "Input image exceeds 20 MiB.")
        data.extend(chunk)
    return bytes(data)


def _id(value: Any) -> str:
    id_ = numeric_id(value)
    if not id_:
        raise XError("invalid_payload", "A numeric X identifier string is required.")
    return id_


def _publish(operation: str, options: dict, connection: dict, deadline: float) -> dict:
    validated = text.validate_post(options.get("text"), options.get("canonical_url"))
    if not validated["valid"]:
        raise XError("invalid_post", "Post exceeds ordinary X limits or contains invalid text.")
    body: dict[str, Any] = {"text": validated["text"]}
    if operation == "reply_to_post":
        parent = _id(options.get("reply_to_post_id"))
        config = connection.get("config") or {}
        if options.get("automated") is True and not all(
            config.get(key) is True
            for key in [
                "automated_replies_enabled",
                "x_ai_reply_permission_confirmed",
                "owner_auto_reply_consent",
            ]
        ):
            raise XError(
                "forbidden", "Automatic AI replies require X written permission and owner consent."
            )
        body["reply"] = {"in_reply_to_tweet_id": parent}
    media = options.get("media_ids")
    if media is not None:
        if not isinstance(media, list) or len(media) > 1:
            raise XError("invalid_payload", "This release supports one static image per post.")
        if media:
            body["media"] = {"media_ids": [_id(item) for item in media]}
    user = XClient(
        str((connection.get("secrets") or {}).get("access_token") or ""), deadline=deadline
    )
    data = user.request("POST", "/2/tweets", body=body).get("data") or {}
    if not isinstance(data, dict):
        raise XError(
            "timeout_unknown",
            "X mutation returned malformed data; reconcile before retry.",
            unknown=True,
        )
    id_ = numeric_id(data.get("id"))
    if not id_:
        raise XError(
            "timeout_unknown",
            "X may have published the post but returned no stable ID.",
            unknown=True,
        )
    return {
        "ok": True,
        "result": {
            "post_id": id_,
            "url": "https://x.com/i/web/status/" + id_,
            "text": data.get("text", validated["text"]),
        },
        "external_effect_status": "succeeded",
        "definitely_no_external_effect": False,
    }


def _upload(payload: dict, options: dict, connection: dict, deadline: float) -> dict:
    body = _artifact(payload, options)
    images.validate_upload(body)
    alt = options.get("alt_text")
    if alt is not None and (not isinstance(alt, str) or len(alt) > 1000):
        raise XError(
            "invalid_payload", "Image alt text must be a string of at most 1000 characters."
        )
    user = XClient(
        str((connection.get("secrets") or {}).get("access_token") or ""), deadline=deadline
    )
    data = (
        user.request(
            "POST",
            "/2/media/upload",
            body={
                "media": base64.b64encode(body).decode("ascii"),
                "media_category": "tweet_image",
            },
        ).get("data")
        or {}
    )
    if not isinstance(data, dict):
        raise XError(
            "timeout_unknown",
            "X mutation returned malformed data; reconcile before retry.",
            unknown=True,
        )
    id_ = numeric_id(data.get("id"))
    if not id_:
        raise XError(
            "timeout_unknown",
            "X media upload returned no stable ID; reconcile before retry.",
            unknown=True,
        )
    if alt:
        try:
            user.request(
                "POST",
                "/2/media/metadata",
                body={"id": id_, "metadata": {"alt_text": {"text": alt}}},
            )
        except XError:
            raise XError(
                "timeout_unknown",
                "Media uploaded but alt-text result is incomplete; reconcile before retry.",
                unknown=True,
                details={"result": {"media_id": id_}},
            ) from None
    return {
        "ok": True,
        "result": {
            "media_id": id_,
            "media_ids": [id_],
            "expires_after_secs": data.get("expires_after_secs"),
        },
        "external_effect_status": "succeeded",
        "definitely_no_external_effect": False,
    }
