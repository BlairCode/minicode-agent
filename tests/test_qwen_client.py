from __future__ import annotations

from types import SimpleNamespace

from minicode_agent.config import ModelConfig
from minicode_agent.llm import QwenClient


class FakeCompletions:
    def __init__(self, response) -> None:
        self.response = response
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def test_qwen_tool_call_is_normalized() -> None:
    raw_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(name="read_file", arguments='{"path":"main.py"}'),
    )
    message = SimpleNamespace(content="I will inspect the file.", tool_calls=[raw_call])
    response = SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="tool_calls")])
    completions = FakeCompletions(response)
    client = QwenClient(ModelConfig())
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = client.complete([{"role": "user", "content": "inspect"}], [])

    assert result.tool_calls[0].name == "read_file"
    assert result.tool_calls[0].arguments == {"path": "main.py"}
    assert result.finish_reason == "tool_calls"
    assert completions.kwargs["model"] == "qwen-plus"


def test_qwen_invalid_arguments_become_dispatchable_error() -> None:
    raw_call = SimpleNamespace(
        id="call-2",
        function=SimpleNamespace(name="read_file", arguments="{broken"),
    )
    message = SimpleNamespace(content=None, tool_calls=[raw_call])
    response = SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="tool_calls")])
    client = QwenClient(ModelConfig())
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions(response)))

    result = client.complete([], [])

    assert result.tool_calls[0].arguments is None
    assert result.tool_calls[0].parse_error

