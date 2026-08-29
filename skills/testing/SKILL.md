---
name: testing
description: Design and run focused automated tests for changed behavior, regressions, boundaries, and failures. Use when implementing tests or verifying code changes across supported languages.
---

# Testing

Build confidence from observable behavior, not from test count or implementation-shaped assertions.

## Choose the right scope

- Start from the user-visible contract or the reproduced failure.
- Prefer a unit test for deterministic local logic, an integration test for component boundaries, and an end-to-end test only when the interaction itself is the risk.
- Extend the repository's existing test layout and helpers before creating a new harness.
- Keep fixtures small and explicit. Use temporary directories and in-memory fakes for local boundaries; mock only the external behavior the test does not own.

## Test design

- Cover the normal path, meaningful boundary values, malformed input, and expected failure behavior.
- For regressions, make the test fail for the original cause and pass for the intended fix.
- Assert outcomes and durable contracts rather than private call order, incidental formatting, timing guesses, or internal implementation details.
- Make nondeterminism controllable: inject clocks, random seeds, identifiers, model responses, and external clients where the code permits it.
- Do not call paid APIs, use real credentials, write to user directories, or depend on network access in the default test suite.
- Avoid sleeps for synchronization. Poll a documented state with a deadline or use an event exposed by the component.
- Keep tests independent and safe to run in any order. Clean up processes, servers, files, and environment changes in failure paths.

## Failure analysis

1. Reproduce the failure and retain the exact command, exit code, stdout, and stderr.
2. Determine whether the product, test expectation, fixture, or environment is wrong.
3. Fix the narrow cause. Do not weaken an assertion merely to turn the suite green.
4. Rerun the focused test, then the relevant suite.
5. If a failure is environmental, show the evidence and identify the missing prerequisite.

## Reporting

- Name the checks that ran and report passed, failed, skipped, or unverified status accurately.
- Mention important scenarios covered by new tests without listing every assertion.
- Never imply that compilation, browser behavior, or external integration was tested when only a unit test ran.

Generated test artifacts must stay in the repository's configured temporary or ignored output locations.
