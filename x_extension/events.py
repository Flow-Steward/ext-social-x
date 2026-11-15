"""Normalize verified direct reply events without fetching or sending anything."""

from __future__ import annotations

import hashlib
from typing import Any

from .client import XError


def numeric_id(value: Any) -> str:
    return (
        value
        if isinstance(value, str) and value.isascii() and value.isdigit() and 1 <= len(value) <= 25
        else ""
    )


def verified_subject(connection: dict) -> str:
    config = connection.get("config") or {}
    identity = config.get("oauth") or {}
    subject = numeric_id(identity.get("subject"))
    if not subject or identity.get("lifecycle_status") != "connected":
        raise XError(
            "invalid_connection", "Reconnect the X account to establish verified identity."
        )
    return subject


def receive_event(options: dict, connection: dict) -> dict:
    callback = options.get("callback") or {}
    request = options.get("request") or {}
    connection_id = connection.get("connection_id")
    if (
        callback.get("authenticated") is not True
        or callback.get("callback_id") != "events"
        or request.get("method") != "POST"
        or not connection_id
        or callback.get("connection_id") != connection_id
    ):
        raise XError(
            "invalid_payload", "An authenticated, exact-connection X POST callback is required."
        )
    subject = verified_subject(connection)
    event = (request.get("json") or {}).get("data")
    if not isinstance(event, dict):
        raise XError("invalid_payload", "An X Activity event envelope is required.")
    if event.get("event_type") != "post.reply.create":
        return {"ok": True, "result": {"status": "ignored"}, "events": []}
    post = event.get("payload") or {}
    filter_ = event.get("filter") or {}
    comment = numeric_id(post.get("id"))
    author = numeric_id(post.get("author_id"))
    parent = numeric_id(post.get("in_reply_to_tweet_id"))
    if not parent:
        parent = next(
            (
                numeric_id(row.get("id"))
                for row in post.get("referenced_tweets") or []
                if isinstance(row, dict) and row.get("type") == "replied_to"
            ),
            "",
        )
    if (
        filter_.get("user_id") != subject
        or author == subject
        or (post.get("in_reply_to_user_id") and post.get("in_reply_to_user_id") != subject)
    ):
        return {"ok": True, "result": {"status": "ignored"}, "events": []}
    if not comment or not author or not parent:
        raise XError(
            "invalid_payload", "Direct reply event is missing stable comment, author or parent ID."
        )
    text = post.get("text")
    if text is not None and (not isinstance(text, str) or len(text) > 100_000):
        raise XError("invalid_payload", "Comment text must be a bounded string.")
    correlation = "x-comment:" + hashlib.sha256((subject + ":" + comment).encode()).hexdigest()
    return {
        "ok": True,
        "result": {"status": "received"},
        "events": [
            {
                "event_type": "x.comment.received",
                "correlation_id": correlation,
                "severity": "info",
                "summary": "New direct reply to the connected X account",
                "metadata": {"event_uuid": event.get("event_uuid")},
                "payload": {
                    "connection_id": connection_id,
                    "account_user_id": subject,
                    "comment_id": comment,
                    "comment_text": text,
                    "author_user_id": author,
                    "parent_post_id": parent,
                    "conversation_id": numeric_id(post.get("conversation_id")) or None,
                    "created_at": post.get("created_at"),
                    "comment_url": "https://x.com/i/web/status/" + comment,
                    "parent_post_url": "https://x.com/i/web/status/" + parent,
                },
            }
        ],
    }
