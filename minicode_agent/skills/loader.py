from __future__ import annotations

import re
from pathlib import Path


class SkillLoadError(ValueError):
    pass


class SkillLoader:
    VALID_NAME = re.compile(r"^[a-zA-Z0-9_-]+$")

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
            sections.append(text)
        return "# Enabled skills\n\n" + "\n\n---\n\n".join(sections) if sections else ""

