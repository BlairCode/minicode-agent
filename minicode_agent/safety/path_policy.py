from __future__ import annotations

from pathlib import Path, PureWindowsPath
from typing import Callable


class PathPolicyError(PermissionError):
    """Raised when a requested path crosses the configured boundary."""


class PathPolicy:
    def __init__(
        self,
        workspace: str | Path,
        *,
        allow_outside_workspace: bool = False,
        outside_approval: Callable[[Path], bool] | None = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.allow_outside_workspace = allow_outside_workspace
        self.outside_approval = outside_approval

    def resolve(
        self,
        user_path: str,
        *,
        must_exist: bool = False,
        expect_directory: bool | None = None,
    ) -> Path:
        if not isinstance(user_path, str) or not user_path.strip():
            raise PathPolicyError("path must be a non-empty string")
        if "\x00" in user_path:
            raise PathPolicyError("path contains a null byte")
        host_path = Path(user_path)
        windows_path = PureWindowsPath(user_path)
        if windows_path.drive and not host_path.drive:
            raise PathPolicyError("path is outside the workspace")
        raw = Path(user_path.replace("\\", "/"))
        candidate = raw if raw.is_absolute() else self.workspace / raw
        try:
            resolved = candidate.resolve(strict=must_exist)
        except OSError as exc:
            raise PathPolicyError(f"cannot resolve path: {exc}") from exc

        outside = False
        try:
            resolved.relative_to(self.workspace)
        except ValueError:
            outside = True
        if outside:
            if not self.allow_outside_workspace:
                raise PathPolicyError("path is outside the workspace")
            if self.outside_approval is None or not self.outside_approval(resolved):
                raise PathPolicyError("outside-workspace access was not approved")

        if must_exist and not resolved.exists():
            raise PathPolicyError("path does not exist")
        if expect_directory is True and resolved.exists() and not resolved.is_dir():
            raise PathPolicyError("path is not a directory")
        if expect_directory is False and resolved.exists() and not resolved.is_file():
            raise PathPolicyError("path is not a file")
        return resolved

    def display(self, path: Path) -> str:
        try:
            return path.relative_to(self.workspace).as_posix() or "."
        except ValueError:
            return str(path)
