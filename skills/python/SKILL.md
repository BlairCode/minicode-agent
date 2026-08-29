---
name: python
description: Implement, review, debug, and test Python code while preserving the repository's conventions. Use for Python source, packaging, command-line tools, services, and automation.
---

# Python engineering

Produce maintainable Python that fits the current project and can be verified in its real environment.

## Before editing

- Inspect `pyproject.toml`, dependency files, nearby modules, and relevant tests before choosing an implementation style.
- Follow the supported Python version and existing formatter, linter, typing, and test conventions.
- Reuse established abstractions and dependencies. Add a package only when the standard library and current dependencies cannot solve the problem cleanly.
- Keep the change within the requested behavior. Do not mix a feature or bug fix with unrelated modernization.

## Implementation rules

- Prefer small functions with explicit inputs and outputs. Use classes when state, lifecycle, or a stable interface justifies them.
- Add type hints at public boundaries and where they clarify non-obvious data shapes. Avoid annotation noise for trivial local values.
- Use `pathlib.Path` for filesystem boundaries and explicit encodings for text files.
- Validate external input near the boundary and raise exceptions that explain what the caller can correct.
- Catch only exceptions that can be handled meaningfully. Preserve the original cause with `raise ... from exc` when translating errors.
- Use context managers for files, locks, temporary resources, and connections. Ensure cleanup also runs on cancellation or failure.
- Keep imports explicit and free of side effects. Avoid mutable default arguments, wildcard imports, and hidden global state.
- Preserve async boundaries. Do not place blocking I/O in an event loop without an executor or an existing project mechanism.
- Add comments only for constraints, invariants, or surprising decisions. Prefer clear names and short docstrings over narration.

## Security and reliability

- Treat paths, command arguments, network responses, serialized data, and environment variables as untrusted input.
- Never embed credentials or personal machine paths in source, examples, fixtures, or logs.
- Avoid `shell=True`, unsafe deserialization, dynamic `eval`/`exec`, and broad filesystem access unless the task explicitly requires them and the project already contains a controlled boundary.
- Keep error messages useful without exposing secrets or full sensitive payloads.

## Verification

1. Run the narrowest test that exercises the changed behavior.
2. Run the repository's formatter, linter, or type checker when configured and relevant.
3. Run the broader Python test suite when the change affects shared code.
4. For packaging or entry-point changes, verify import and startup behavior from the documented command.
5. Report the exact commands and results. Do not claim success from code inspection alone.

If a required dependency, service, credential, or platform is unavailable, complete all offline checks and state the remaining verification gap precisely.
