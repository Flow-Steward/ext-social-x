"""The installed Support tab resolves from the same manifest as the bundle."""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/Flow-Steward/ext-social-x"


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_support_is_registered_for_manifest_and_descriptor_import():
    manifest = load(ROOT / "extension.yaml")
    descriptor = load(ROOT / "extension-descriptor.yaml")
    # The strict descriptor has no UI field. The host imports the co-located
    # root extension.yaml; preserve the existing artifact declarations.
    assert "ui_manifest" not in descriptor
    assert manifest["vendor"]["support_url"] == REPOSITORY + "/issues"
    assert descriptor["vendor"]["support_url"] == REPOSITORY + "/issues"
    ui_path = ROOT / manifest["ui_manifest"]
    pages = [load(ui_path.parent / entry["ref"]) for entry in load(ui_path)["pages"]]
    support = [page for page in pages if page["page_id"] == "support"]
    assert len(support) == 1
    assert support[0]["title"] == "Support"
    assert support[0]["project_scoped"] is False
    assert "connection" not in support[0]
    components = support[0]["components"]
    assert len(components) == 2
    assert all(component["type"] == "markdown" for component in components)
    body = "\n".join(component["body"] for component in components)
    assert set(re.findall(r"\]\((https://[^)]+)\)", body)) == {
        REPOSITORY + "/issues/new/choose",
        REPOSITORY + "/issues",
        REPOSITORY,
    }
    for phrase in (
        "extension version",
        "Flow Steward version",
        "expected",
        "exact error message",
        "workflow, step or action",
        "when it happened",
        "Monitoring → Download diagnostics",
        "review before sharing",
        "Issues are public",
        "passwords",
        "API keys",
        "tokens",
        "connection strings",
        "customer data",
    ):
        assert phrase in body


@pytest.mark.skipif(not Path("/app/core").is_dir(), reason="requires fs-audit host")
def test_actual_descriptor_import_keeps_support_and_runtime_contracts(monkeypatch):
    monkeypatch.syspath_prepend("/app")
    from core.application.extensions.command_core import _descriptor_with_bundle_runtime
    from core.infrastructure.extension_runtime.extension_runtime_compile import (
        compile_extension_bundle,
    )
    from core.infrastructure.extension_runtime.extension_runtime_entrypoints import (
        normalize_extension_row_for_runtime,
    )

    descriptor = load(ROOT / "extension-descriptor.yaml")
    imported, errors = _descriptor_with_bundle_runtime(
        descriptor_path=ROOT / "extension-descriptor.yaml",
        normalized_descriptor=descriptor,
    )
    assert errors == []
    direct = compile_extension_bundle(
        ROOT, logical_bundle_dir_name=descriptor["extension_id"].replace(".", "_").replace("-", "_")
    )
    assert direct["status"] == "valid", direct
    compiled = direct["compiled_manifest"]
    projected = normalize_extension_row_for_runtime({"compiled_manifest": compiled})
    assert projected["ui_manifest"] == compiled["ui_manifest"]
    support = [p for p in projected["ui_manifest"]["pages"] if p["page_id"] == "support"]
    assert len(support) == 1
    assert support[0]["project_scoped"] is False
    for field in ("action_definitions", "query_definitions", "connection_types", "callbacks"):
        assert imported.get(field) == compiled.get(field), field
