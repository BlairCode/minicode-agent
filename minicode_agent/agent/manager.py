from __future__ import annotations

from pathlib import Path

from minicode_agent.config import CodingConfig, LeetCodeConfig

from .spec import AgentSpec


ALL_TOOLS = frozenset(
    {"read_file", "write_file", "patch_file", "list_directory", "search_files", "run_command"}
)


class AgentManager:
    def __init__(
        self,
        prompt_root: str | Path,
        leetcode: LeetCodeConfig,
        coding: CodingConfig,
    ) -> None:
        self.prompt_root = Path(prompt_root)
        self.leetcode = leetcode
        self.coding = coding

    def _read_prompt(self, name: str) -> str:
        path = self.prompt_root / f"{name}.md"
        return path.read_text(encoding="utf-8")

    def get(self, name: str) -> AgentSpec:
        if name == "coding":
            preferences = (
                f"User preferences: default language={self.coding.default_language}; "
                f"code style={self.coding.code_style}; comment level={self.coding.comment_level}; "
                f"comment language={self.coding.comment_language}. "
                f"Prefer existing project style={self.coding.prefer_existing_style}."
            )
            return AgentSpec(
                name="coding",
                description="General project coding and debugging",
                system_prompt=self._read_prompt("coding") + "\n\n" + preferences,
                enabled_tools=ALL_TOOLS,
                enabled_skills=("python", "cpp", "testing", "debugging"),
            )
        if name == "leetcode":
            settings = (
                f"Current mode: {self.leetcode.mode}. Language: {self.leetcode.language}. "
                f"Generate tests: {self.leetcode.generate_tests}. "
                f"Save solution: {self.leetcode.save_solution}. "
                f"Include complexity: {self.leetcode.include_complexity}."
            )
            return AgentSpec(
                name="leetcode",
                description="Algorithm problem solving, hints, interviews, and code review",
                system_prompt=self._read_prompt("leetcode") + "\n\n" + settings,
                enabled_tools=ALL_TOOLS,
                enabled_skills=(self.leetcode.language, "testing", "debugging", "leetcode"),
            )
        raise ValueError(f"unknown agent: {name}")
