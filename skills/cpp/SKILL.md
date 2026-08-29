---
name: cpp
description: Implement, review, debug, and test modern C++ while respecting the repository's language standard, build system, ownership model, and performance constraints.
---

# C++ engineering

Write correct, portable C++ that preserves the project's build and ownership conventions.

## Before editing

- Inspect the build system, configured C++ standard, compiler flags, nearby headers and sources, and existing tests.
- Follow the repository's naming, namespace, header layout, error-handling, and formatting style.
- Identify ownership, lifetime, threading, ABI, and performance constraints before changing an interface.
- Avoid broad header or template changes when a local implementation is enough; they increase rebuild cost and compatibility risk.

## Implementation rules

- Prefer RAII, value semantics, standard containers, algorithms, and smart pointers with clear ownership.
- Use references or non-owning views only when the referenced lifetime is evident. Do not return dangling views, references, or iterators.
- Make constructors establish valid invariants. Use `const`, `constexpr`, `noexcept`, and `[[nodiscard]]` where they express a real contract.
- Prevent signed/unsigned errors, integer overflow, invalid shifts, out-of-bounds access, and unchecked narrowing at input boundaries.
- Prefer scoped enums and explicit conversions. Avoid macros except for build integration or existing project patterns.
- Keep public headers self-contained and minimize transitive includes. Put implementation details in source files when possible.
- Use project-standard error handling. Do not mix exceptions, status values, and process termination without a clear boundary.
- For concurrent code, document the synchronization invariant and keep lock scope narrow. Avoid callbacks while holding locks unless the design requires it.
- Do not introduce compiler-specific extensions unless the project already depends on them or the code has a portable fallback.

## Performance

- Start with the required complexity and data scale; do not trade clarity for speculative micro-optimizations.
- Avoid accidental copies in hot paths, but use moves and views only when lifetime remains obvious.
- Measure or benchmark when performance is the task. State the dataset, build mode, and command used.

## Verification

1. Build the smallest affected target with the configured standard and warning level.
2. Run focused tests, including empty, minimum, maximum, duplicate, overflow, and invalid inputs where relevant.
3. Run sanitizer builds when memory safety or undefined behavior is involved and the toolchain supports them.
4. Run broader project tests after shared headers, templates, or build configuration change.
5. Report compiler, command, exit status, and any platform limitation.

Never describe code as compiled or sanitizer-clean unless those checks actually ran.
