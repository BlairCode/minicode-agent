from __future__ import annotations

from pathlib import Path

import pytest

from minicode_agent.skills.loader import SkillLoadError, SkillLoader


SKILL_NAMES = ("python", "cpp", "testing", "debugging", "leetcode")


def test_project_skills_use_valid_frontmatter() -> None:
    root = Path(__file__).resolve().parents[1] / "skills"
    loaded = SkillLoader(root).load(SKILL_NAMES)

    for name in SKILL_NAMES:
        assert f"name: {name}" in loaded
    assert loaded.startswith("# Enabled skills")


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("# Missing frontmatter", "missing YAML frontmatter"),
        ("---\nname: wrong\ndescription: useful\n---\n# Body", "name must match"),
        ("---\nname: demo\n---\n# Body", "requires a description"),
    ],
)
def test_skill_loader_rejects_nonstandard_metadata(tmp_path: Path, content: str, message: str) -> None:
    skill = tmp_path / "demo"
    skill.mkdir()
    (skill / "SKILL.md").write_text(content, encoding="utf-8")

    with pytest.raises(SkillLoadError, match=message):
        SkillLoader(tmp_path).load(["demo"])
