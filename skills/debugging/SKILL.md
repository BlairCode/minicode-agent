---
name: debugging
description: Diagnose reproducible software failures using logs, traces, tests, and controlled experiments, then apply and verify the smallest justified fix.
---

# Evidence-driven debugging

Find the first incorrect state or boundary, not merely the last visible symptom.

## Investigation loop

1. Restate the observed failure, expected behavior, environment, and reproduction command.
2. Reproduce it when safe. Preserve the exact error, exit code, relevant log lines, and input.
3. Trace the failing path from the external boundary toward the first violated invariant.
4. Form one falsifiable hypothesis tied to evidence.
5. Run the smallest inspection or experiment that distinguishes that hypothesis from alternatives.
6. Change the narrow cause, add a regression test when practical, and rerun the original reproduction.

## Diagnostic rules

- Read the nearest caller, callee, configuration, and tests before editing.
- Separate product defects from stale processes, bad local state, unsupported versions, missing credentials, and incorrect test assumptions.
- Check recent or working-tree changes without overwriting unrelated user work.
- Prefer structured logs, debugger output, traces, and minimal probes over speculative edits.
- Do not repeat an unchanged failing action. Change the hypothesis, input, environment, or observation point.
- Treat timeouts and intermittent failures as state or synchronization problems until evidence shows otherwise; do not simply increase timeouts.
- Follow data across serialization, path, encoding, process, thread, and network boundaries where representation can change.
- Redact secrets and personal paths from shared diagnostics. Never print whole environments or credential stores.

## Fix quality

- Preserve documented behavior for unaffected inputs.
- Avoid catch-all exception handling, silent fallback, disabled validation, or weaker tests as substitutes for a fix.
- Add an explanatory comment only when the corrected invariant would otherwise remain surprising.
- If the root cause is outside the repository, improve the local error message or guard only when that is within the task.

## Stop conditions

Finish when the original failure no longer reproduces, focused regression coverage passes, and relevant broader checks remain healthy. If reproduction needs unavailable hardware, credentials, network access, or user state, complete the available static and isolated checks and report exactly what remains unverified.
