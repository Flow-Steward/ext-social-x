"""Cross-surface contract requirements for the independently packaged extension."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    return yaml.safe_load((ROOT / name).read_text())


def test_visible_actions_have_identical_v2_ids():
    actions = load("ui/actions/actions.yaml")["actions"]
    operations = load("contracts/operation_manifest.yaml")["operations"]
    visible = {item["action_id"] for item in actions if item.get("workflow_visible")}
    assert visible == {item["operation_id"] for item in operations if item.get("workflow_visible")}
    assert visible == {
        "validate_post",
        "prepare_image",
        "upload_media",
        "publish_post",
        "get_post",
        "reply_to_post",
    }


def test_identity_version_callbacks_and_effect_claim():
    manifest = load("extension.yaml")
    descriptor = load("extension-descriptor.yaml")
    assert manifest["extension_id"] == descriptor["extension_id"] == "flowsteward.x"
    assert manifest["version"] == descriptor["release_version"] == "1.0.0"
    assert manifest["kind"] == "tool_provider"
    assert "ingress_event" not in manifest["features"]
    callback = next(item for item in manifest["callbacks"] if item["callback_id"] == "events")
    assert callback["connection_scoped"] is True
    assert callback["auth"]["type"] == "hmac_sha256_body"
    assert callback["auth"]["signature_prefix"] == "sha256="
    assert callback["auth"]["key_source"]["provider_id"] == "x_oauth"
    effect = next(
        item for item in manifest["external_effects"] if item["operation_id"] == "reply_to_post"
    )
    assert effect["business_key_field"] == "reply_to_post_id"
    assert effect["test_mode_behavior"] == "suppress"
    trigger = manifest["workflow_triggers"][0]
    assert trigger["event_name"] == "x.comment.received"
    assert trigger["config_schema"]["required"] == ["connection_id"]


def test_default_disabled_automation_and_scopes():
    connection = load("contracts/connection_types.yaml")["connection_types"][0]
    assert set(connection["auth"]["scopes"]["required"]) >= {
        "tweet.read",
        "tweet.write",
        "users.read",
        "media.write",
        "offline.access",
    }
    for key in (
        "automated_replies_enabled",
        "x_ai_reply_permission_confirmed",
        "owner_auto_reply_consent",
    ):
        assert connection["config_schema"]["properties"][key]["default"] is False
    workflow = load("artifacts/workflows/x_review_comment.yaml")
    assert workflow["enabled"] is False
    assert any(step["step_kind"] == "approval" for step in workflow["steps"])
    send = next(step for step in workflow["steps"] if step["step_id"] == "send_reply")
    assert send["input_mapping_jsonb"]["reply_to_post_id"] == "state.inputs.comment_id"


def test_portable_pinned_wheel_hashes():
    import hashlib

    manifest = load("extension.yaml")
    for requirement in manifest["python_requirements"]:
        files = list(
            (ROOT / "wheels").glob(requirement["name"].lower().replace("-", "_") + "-*.whl")
        )
        assert files
        assert any("any.whl" in file.name for file in files) or all(
            any(arch in file.name for file in files) for arch in ["x86_64", "aarch64"]
        )
        for file in files:
            assert (
                "sha256:" + hashlib.sha256(file.read_bytes()).hexdigest() in requirement["hashes"]
            )


def test_workflow_graphs_resolve_every_step_and_keep_human_approval():
    for name in ["x_publish_article", "x_review_comment"]:
        workflow = load("artifacts/workflows/" + name + ".yaml")
        steps = {step["step_id"]: step for step in workflow["steps"]}
        graph = workflow["settings"]["execution_graph"]
        assert graph["entry"]["id"] in steps
        for edge in graph["edges"]:
            assert edge["source"]["id"] in steps
            assert edge["target"]["id"] in steps
        seen = {graph["entry"]["id"]}
        for _ in steps:
            for edge in graph["edges"]:
                if edge["source"]["id"] in seen:
                    seen.add(edge["target"]["id"])
        assert seen == set(steps)
        for step in steps.values():
            operation = (step.get("override") or {}).get("connector") or {}
            if operation.get("action_id") in {"publish_post", "reply_to_post"}:
                previous = [
                    steps[edge["source"]["id"]]
                    for edge in graph["edges"]
                    if edge["target"]["id"] == step["step_id"]
                ]
                assert previous and all(item["step_kind"] == "approval" for item in previous)
