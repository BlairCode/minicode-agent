from __future__ import annotations

import re
from pathlib import Path

import yaml


class SkillLoadError(ValueError):
    pass


class SkillLoader:
    VALID_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def load(self, names: tuple[str, ...] | list[str]) -> str:
        sections: list[str] = []
        for name in names:
            if not self.VALID_NAME.fullmatch(name):
                raise SkillLoadError(f"invalid skill name: {name!r}")
            path = (self.root / name / "SKILL.md").resolve()
            try:
                path.relative_to(self.root)
            except ValueError as exc:
                raise SkillLoadError("skill path escaped the skill root") from exc
            if not path.is_file():
                raise SkillLoadError(f"skill not found: {name}")
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                raise SkillLoadError(f"skill is empty: {name}")
            self._validate_frontmatter(name, text)
            sections.append(text)
        return "# Enabled skills\n\n" + "\n\n---\n\n".join(sections) if sections else ""

    @staticmethod
    def _validate_frontmatter(expected_name: str, text: str) -> None:
        if not text.startswith("---\n"):
            raise SkillLoadError(f"skill {expected_name!r} is missing YAML frontmatter")
        marker = text.find("\n---\n", 4)
        if marker < 0:
            raise SkillLoadError(f"skill {expected_name!r} has unterminated YAML frontmatter")
        try:
            metadata = yaml.safe_load(text[4:marker])
        except yaml.YAMLError as exc:
            raise SkillLoadError(f"skill {expected_name!r} has invalid YAML frontmatter") from exc
        if not isinstance(metadata, dict):
            raise SkillLoadError(f"skill {expected_name!r} frontmatter must be a mapping")
        if metadata.get("name") != expected_name:
            raise SkillLoadError(f"skill name must match its directory: {expected_name!r}")
        description = metadata.get("description")
        if not isinstance(description, str) or not description.strip():
            raise SkillLoadError(f"skill {expected_name!r} requires a description")
