"""Agent skills declare the actual quoted text supplied by their workflow steps."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("workflow_id", "step_id", "state"),
    [
        (
            "x_publish_article",
            "draft_announcement",
            {
                "inputs": {
                    "title": "A published article",
                    "content": "Verified article body.",
                    "excerpt": "A short excerpt.",
                    "canonical_url": "https://example.test/article",
                }
            },
        ),
        (
            "x_review_comment",
            "draft_reply",
            {
                "inputs": {"comment_text": "What changed?"},
                "parent_post": {"id": "123", "text": "The connected account's post."},
            },
        ),
    ],
)
def test_skill_inputs_cover_workflow_mappings_with_text_values(workflow_id, step_id, state):
    workflow = yaml.safe_load((ROOT / f"artifacts/workflows/{workflow_id}.yaml").read_text())
    step = next(item for item in workflow["steps"] if item["step_id"] == step_id)
    skill = yaml.safe_load((ROOT / f"artifacts/skills/{step['skill_id']}.yaml").read_text())
    inputs = skill.get("expected_inputs") or []
    mapping = step["input_mapping_jsonb"]
    assert inputs, "Skill must describe the context passed by its workflow"
    assert {item["name"] for item in inputs} == set(mapping)
    for item in inputs:
        value = state
        path = mapping[item["name"]].split(".")
        assert path[0] == "state"
        for part in path[1:]:
            value = value[part]
        assert item["type"] in {"text", "paragraph", "string"}
        assert isinstance(value, str), f"{item['name']} must receive quoted text"
        assert not item["required"] or value


def test_article_skill_keeps_optional_article_body_and_excerpt():
    workflow = yaml.safe_load((ROOT / "artifacts/workflows/x_publish_article.yaml").read_text())
    skill = yaml.safe_load((ROOT / "artifacts/skills/x_article_announcement.yaml").read_text())
    exposed = {item["name"]: item for item in workflow["settings"]["callable"]["expected_inputs"]}
    inputs = {item["name"]: item for item in skill.get("expected_inputs", [])}
    assert inputs
    assert all(item["required"] == exposed[name]["required"] for name, item in inputs.items())
