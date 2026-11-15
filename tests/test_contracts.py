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


def test_artifact_descriptor_inherits_complete_executable_oauth_contract():
    descriptor = load("extension-descriptor.yaml")
    manifest = load("extension.yaml")
    assert descriptor["runtime"].get("extension_contract_v2") is None
    assert descriptor.get("extension_contract_v2") is None
    assert descriptor["artifacts"]["extensions"] == [
        {"extension_id": "flowsteward.x", "ref": "extension.yaml", "publish": True}
    ]
    provider = manifest["runtime"]["extension_contract_v2"]["oauth_providers"][0]
    connection = load("contracts/connection_types.yaml")["connection_types"][0]
    assert provider["provider_id"] == connection["auth"]["provider_id"] == "x_oauth"
    assert any(
        callback["callback_id"] == provider["callback_id"]
        and callback["purpose"] == "oauth_authorization"
        for callback in manifest["callbacks"]
    )
    assert any(
        action["action_id"] == provider["post_connect_action_id"]
        for action in load("ui/actions/actions.yaml")["actions"]
    )


def test_identity_version_callbacks_and_supported_effect_contract():
    manifest = load("extension.yaml")
    descriptor = load("extension-descriptor.yaml")
    assert manifest["extension_id"] == descriptor["extension_id"] == "flowsteward.x"
    assert manifest["version"] == descriptor["release_version"] == "1.0.0"
    assert manifest["kind"] == "tool_provider"
    assert "ingress_event" not in manifest["features"]
    callback = next(item for item in manifest["callbacks"] if item["callback_id"] == "events")
    assert callback["connection_scoped"] is True
    assert callback["auth"]["type"] == "raw_body_hmac_sha256"
    assert callback["auth"]["signature_prefix"] == "sha256="
    assert callback["auth"]["signature_encoding"] == "base64"
    assert callback["auth"]["secret_name"] == "webhook_signing_secret"
    assert callback["auth"]["verification"] == {
        "challenge_parameter": "crc_token",
        "required_parameters": {},
        "response": "hmac",
        "response_field": "response_token",
    }
    assert "setup" not in callback
    assert manifest["runtime"]["compatibility"]["platform_min"] == "1.9.0"
    assert descriptor["runtime"]["compatibility"]["platform_min"] == "1.9.0"
    effect = next(
        item for item in manifest["external_effects"] if item["operation_id"] == "reply_to_post"
    )
    assert "business_key_field" not in effect
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


def test_named_connection_signing_secret_separate_from_app_bearer():
    connection = load("contracts/connection_types.yaml")["connection_types"][0]
    assert connection["secret_schema"]["properties"]["webhook_signing_secret"]["type"] == "string"
    assert "app_bearer_token" not in connection["secret_schema"]["properties"]
    assert "app_bearer_token" in load("schemas/secrets.schema.yaml")["properties"]


def test_manager_setup_actions_report_processed_lifecycle_status():
    actions = {row["action_id"]: row for row in load("ui/actions/actions.yaml")["actions"]}
    operations = {
        row["operation_id"]: row for row in load("contracts/operation_manifest.yaml")["operations"]
    }
    for name in ("configure_webhook", "get_webhook_status", "remove_webhook"):
        assert actions[name]["workflow_visible"] is False
        assert {"status", "configured", "reconciliation_required", "error"} <= set(
            actions[name]["result_fields"]
        )
        assert {"status", "configured", "reconciliation_required", "error"} <= {
            field["name"] for field in operations[name]["outputs"]
        }
