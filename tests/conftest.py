from __future__ import annotations

from collections import deque

import pytest

from minicode_agent.config import AppConfig
from minicode_agent.llm.types import ModelResponse


class ScriptedLLM:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = deque(responses)
        self.calls: list[tuple[list[dict], list[dict]]] = []

    def complete(self, messages, tools) -> ModelResponse:
        self.calls.append((list(messages), list(tools)))
        if not self.responses:
            raise AssertionError("scripted model has no response left")
        return self.responses.popleft()


@pytest.fixture
def config(tmp_path) -> AppConfig:
    value = AppConfig()
    value.workspace.root = str(tmp_path / "workspace")
    value.storage.data_dir = str(tmp_path / "personal-data")
    value.security.command_mode = "strict"
    value.agent.retry_base_seconds = 0
    value.model.max_retries = 0
    return value
