---
name: leetcode
description: Solve, hint, interview, or review algorithm problems with explicit invariants, complexity analysis, executable tests, and mode-appropriate disclosure.
---

# Algorithm problems

Match the configured mode while keeping the reasoning, implementation, and verification technically complete.

## Establish the problem

- Extract the input contract, output contract, constraints, mutation rules, and required interface from the prompt or starter code.
- Clarify only ambiguities that change the algorithm or required output. Otherwise state a reasonable assumption and proceed.
- Work through a small example and identify the invariant before selecting a data structure.
- Use the constraints to reject solutions that exceed expected time or memory limits.

## Modes

### Solve

Explain the core idea and invariant, implement the requested interface, run focused tests, repair failures, and report time and auxiliary space complexity separately.

### Hint

Give one progressive hint at a time. Begin with the observation or invariant, then the data structure, then pseudocode only if requested. Do not reveal complete code unless the user asks to leave hint mode.

### Interview

Ask concise questions that let the candidate drive the solution. Challenge complexity and edge cases, offer a small nudge after a stalled attempt, and wait for the candidate before presenting a finished approach.

### Review

Read the submitted algorithm as written. Find the smallest counterexample, explain the violated invariant, and propose a focused correction. Preserve a valid approach instead of replacing it only because another solution is more familiar.

## Implementation rules

- Cover empty or minimum inputs, duplicates, sorted or adversarial order, disconnected data, overflow, and worst-case depth when applicable.
- Distinguish value range from collection length. Use a numeric type that safely holds intermediate results.
- Avoid recursion when constraints can exceed the language's safe stack depth unless an iterative alternative is impractical.
- Keep judge-facing signatures and required class names unchanged.
- Do not depend on non-standard libraries unless the target platform supports them.
- When saving is enabled, place source, tests, and explanation under `leetcode/<problem-slug>/` without overwriting unrelated work.

## Verification and reporting

1. Run examples plus focused boundary and adversarial cases.
2. Compile or execute with the repository's configured language version.
3. For optimized algorithms, compare against a simple reference implementation on small generated cases when practical.
4. State time complexity and auxiliary space, including recursion stack or output storage conventions.
5. Never invent an online judge result. Report only local commands that actually ran.
