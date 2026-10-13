# Project instructions

## Kernel routing

<!-- VIBE:KERNEL_ROUTING_START -->

This project uses committed local copies of the Vibecoding Kernel.

- Always read `.vibe/kernel/OPERATING.md` and choose its maintenance, operation,
  or audit mode before normal project work.
- For version, tag, publish, or release work, also read
  `.vibe/kernel/RELEASE.md`.
- For user corrections, instruction conflicts, reusable agent-workflow lessons,
  kernel proposals, or a newly pulled kernel version, also read
  `.vibe/kernel/EVOLUTION.md`.
- For product behavior or domain logic, read `BUSINESS.md` and only the relevant
  module from `business/*`.
- Do not edit `.vibe/kernel/*` manually or read the parent kernel during normal
  work. Refresh the local copy with `make vibe-pull`.
- When a reusable workflow improvement belongs in the parent, run
  `make vibe-propose`; it appends a reviewable proposal without changing rules.

<!-- VIBE:KERNEL_ROUTING_END -->

## Local rules

Use `make check` for verification. Use `make release` interactively and
`make release-push` for an authorized release. The annotated tag is the
publishing and deployment gate. Read `docs/DEPLOYMENT.md` before VPS operations.
Write all authored artifacts in English. Work personally without subagents.
