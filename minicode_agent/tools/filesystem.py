from __future__ import annotations

import fnmatch
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from minicode_agent.safety.path_policy import PathPolicy

from .base import BaseTool, ToolResult


def _atomic_write(path: Path, content: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = path.stat().st_mode if path.exists() else None
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if existing_mode is not None:
            os.chmod(temporary, existing_mode)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


class FilesystemTool(BaseTool):
    def __init__(
        self,
        path_policy: PathPolicy,
        *,
        max_read_bytes: int = 1_000_000,
        max_output_chars: int = 20_000,
        backup_before_overwrite: bool = False,
    ) -> None:
        self.path_policy = path_policy
        self.max_read_bytes = max_read_bytes
        self.max_output_chars = max_output_chars
        self.backup_before_overwrite = backup_before_overwrite

    def _backup(self, path: Path) -> str | None:
        if not self.backup_before_overwrite or not path.exists():
            return None
        try:
            relative = path.relative_to(self.path_policy.workspace)
        except ValueError:
            return None
        backup = self.path_policy.workspace / ".minicode" / "backups" / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        index = 1
        candidate = backup.with_suffix(backup.suffix + ".bak")
        while candidate.exists():
            index += 1
            candidate = backup.with_suffix(backup.suffix + f".{index}.bak")
        shutil.copy2(path, candidate)
        return self.path_policy.display(candidate)


class ReadFileTool(FilesystemTool):
    name = "read_file"
    description = "Read a UTF-8 text file inside the workspace, optionally by line range."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path"},
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    def execute(self, path: str, start_line: int = 1, end_line: int | None = None) -> ToolResult:
        target = self.path_policy.resolve(path, must_exist=True, expect_directory=False)
        if start_line < 1 or (end_line is not None and end_line < start_line):
            return ToolResult(False, error="invalid line range")
        size = target.stat().st_size
        if size > self.max_read_bytes:
            return ToolResult(False, error=f"file exceeds read limit ({size} bytes)")
        raw = target.read_bytes()
        if b"\x00" in raw[:8192]:
            return ToolResult(False, error="binary files are not supported")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            return ToolResult(False, error=f"file is not valid UTF-8: {exc}")
        lines = text.splitlines(keepends=True)
        selected = lines[start_line - 1 : end_line]
        output = "".join(selected)
        truncated = len(output) > self.max_output_chars
        if truncated:
            output = output[: self.max_output_chars] + "\n... [output truncated]"
        return ToolResult(
            True,
            output=output,
            data={
                "path": self.path_policy.display(target),
                "start_line": start_line,
                "end_line": min(end_line or len(lines), len(lines)),
                "total_lines": len(lines),
                "truncated": truncated,
            },
        )


class WriteFileTool(FilesystemTool):
    name = "write_file"
    description = "Create or atomically replace a UTF-8 text file inside the workspace."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path"},
            "content": {"type": "string"},
            "overwrite": {"type": "boolean", "default": True},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    def execute(self, path: str, content: str, overwrite: bool = True) -> ToolResult:
        content_size = len(content.encode("utf-8"))
        if content_size > self.max_read_bytes:
            return ToolResult(False, error=f"content exceeds write limit ({content_size} bytes)")
        target = self.path_policy.resolve(path, must_exist=False, expect_directory=False)
        existed = target.exists()
        if existed and not overwrite:
            return ToolResult(False, error="file already exists and overwrite is false")
        backup = self._backup(target)
        _atomic_write(target, content)
        return ToolResult(
            True,
            output=f"{'Updated' if existed else 'Created'} {self.path_policy.display(target)}",
            data={"path": self.path_policy.display(target), "bytes": content_size, "backup": backup},
        )


class PatchFileTool(FilesystemTool):
    name = "patch_file"
    description = "Replace an exact text fragment in one workspace file."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_text": {"type": "string"},
            "new_text": {"type": "string"},
            "count": {"type": "integer", "minimum": 1, "default": 1},
        },
        "required": ["path", "old_text", "new_text"],
        "additionalProperties": False,
    }

    def execute(self, path: str, old_text: str, new_text: str, count: int = 1) -> ToolResult:
        if count < 1:
            return ToolResult(False, error="count must be at least 1")
        if not old_text or old_text == new_text:
            return ToolResult(False, error="old_text must be non-empty and differ from new_text")
        target = self.path_policy.resolve(path, must_exist=True, expect_directory=False)
        if target.stat().st_size > self.max_read_bytes:
            return ToolResult(False, error="file exceeds patch size limit")
        try:
            text = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            return ToolResult(False, error=f"file is not valid UTF-8: {exc}")
        occurrences = text.count(old_text)
        if occurrences < count:
            return ToolResult(False, error=f"expected {count} occurrence(s), found {occurrences}")
        updated = text.replace(old_text, new_text, count)
        updated_size = len(updated.encode("utf-8"))
        if updated_size > self.max_read_bytes:
            return ToolResult(False, error=f"patched content exceeds write limit ({updated_size} bytes)")
        backup = self._backup(target)
        _atomic_write(target, updated)
        return ToolResult(
            True,
            output=f"Patched {self.path_policy.display(target)} ({count} replacement(s))",
            data={"path": self.path_policy.display(target), "replacements": count, "backup": backup},
        )


class ListDirectoryTool(FilesystemTool):
    name = "list_directory"
    description = "List files and directories under a workspace path."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "default": "."},
            "max_depth": {"type": "integer", "minimum": 1, "maximum": 5, "default": 2},
            "include_hidden": {"type": "boolean", "default": False},
            "max_entries": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
        },
        "additionalProperties": False,
    }

    def execute(
        self,
        path: str = ".",
        max_depth: int = 2,
        include_hidden: bool = False,
        max_entries: int = 200,
    ) -> ToolResult:
        if not 1 <= max_depth <= 5 or not 1 <= max_entries <= 1000:
            return ToolResult(False, error="list limits are out of range")
        root = self.path_policy.resolve(path, must_exist=True, expect_directory=True)
        entries: list[str] = []
        for current, directories, files in os.walk(root, followlinks=False):
            current_path = Path(current)
            depth = len(current_path.relative_to(root).parts)
            directories[:] = sorted(
                item for item in directories if include_hidden or not item.startswith(".")
            )
            if depth >= max_depth:
                directories[:] = []
            names = [(name, True) for name in directories] + [(name, False) for name in sorted(files)]
            for name, is_dir in names:
                if not include_hidden and name.startswith("."):
                    continue
                candidate = current_path / name
                relative = candidate.relative_to(root).as_posix()
                entries.append(relative + ("/" if is_dir else ""))
                if len(entries) >= max_entries:
                    break
            if len(entries) >= max_entries:
                break
        truncated = len(entries) >= max_entries
        return ToolResult(
            True,
            output="\n".join(entries) or "(empty directory)",
            data={"path": self.path_policy.display(root), "entries": len(entries), "truncated": truncated},
        )


class SearchFilesTool(FilesystemTool):
    name = "search_files"
    description = "Search UTF-8 text files inside the workspace by literal text or regex."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "path": {"type": "string", "default": "."},
            "glob": {"type": "string", "default": "*"},
            "regex": {"type": "boolean", "default": False},
            "case_sensitive": {"type": "boolean", "default": False},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def execute(
        self,
        query: str,
        path: str = ".",
        glob: str = "*",
        regex: bool = False,
        case_sensitive: bool = False,
        max_results: int = 100,
    ) -> ToolResult:
        if not query:
            return ToolResult(False, error="query cannot be empty")
        if not 1 <= max_results <= 500:
            return ToolResult(False, error="max_results is out of range")
        root = self.path_policy.resolve(path, must_exist=True, expect_directory=True)
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(query if regex else re.escape(query), flags)
        except re.error as exc:
            return ToolResult(False, error=f"invalid regex: {exc}")
        matches: list[str] = []
        skipped = 0
        for current, directories, files in os.walk(root, followlinks=False):
            directories[:] = sorted(item for item in directories if item not in {".git", ".minicode"})
            for name in sorted(files):
                if not fnmatch.fnmatch(name, glob):
                    continue
                candidate = Path(current) / name
                try:
                    candidate = self.path_policy.resolve(str(candidate), must_exist=True, expect_directory=False)
                    if candidate.stat().st_size > self.max_read_bytes:
                        skipped += 1
                        continue
                    raw = candidate.read_bytes()
                    if b"\x00" in raw[:8192]:
                        skipped += 1
                        continue
                    text = raw.decode("utf-8")
                except (OSError, UnicodeDecodeError):
                    skipped += 1
                    continue
                display = candidate.relative_to(root).as_posix()
                for number, line in enumerate(text.splitlines(), 1):
                    if pattern.search(line):
                        snippet = line.strip()
                        if len(snippet) > 300:
                            snippet = snippet[:300] + "..."
                        matches.append(f"{display}:{number}: {snippet}")
                        if len(matches) >= max_results:
                            break
                if len(matches) >= max_results:
                    break
            if len(matches) >= max_results:
                break
        return ToolResult(
            True,
            output="\n".join(matches) or "No matches found.",
            data={"matches": len(matches), "truncated": len(matches) >= max_results, "skipped_files": skipped},
        )
