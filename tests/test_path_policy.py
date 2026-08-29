from pathlib import Path

import pytest

from minicode_agent.safety import PathPolicy, PathPolicyError


def test_allows_workspace_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "src" / "app.py"
    policy = PathPolicy(workspace)
    assert policy.resolve("src/app.py") == target.resolve()


@pytest.mark.parametrize(
    "value",
    [
        "../secret.txt",
        "../../outside",
        "..\\outside.txt",
        "src\\..\\..\\outside.txt",
        "C:\\outside.txt",
    ],
)
def test_rejects_path_traversal(tmp_path: Path, value: str) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(PathPolicyError, match="outside"):
        PathPolicy(workspace).resolve(value)


def test_accepts_windows_separators_inside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "src" / "app.py"
    assert PathPolicy(workspace).resolve("src\\app.py") == target.resolve()


def test_outside_access_requires_explicit_approval(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    denied = PathPolicy(workspace, allow_outside_workspace=True, outside_approval=lambda _path: False)
    with pytest.raises(PathPolicyError, match="not approved"):
        denied.resolve(str(outside))
    allowed = PathPolicy(workspace, allow_outside_workspace=True, outside_approval=lambda path: path == outside)
    assert allowed.resolve(str(outside)) == outside.resolve()
