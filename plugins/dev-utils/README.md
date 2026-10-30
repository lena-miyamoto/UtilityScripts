# dev-utils

Claude Code skills for reviewing a changeset, applying approved fixes, optimizing this repo's
instruction, skill, and plugin files, and inspecting or transforming CSV/TSV data.

## Install

```bash
claude plugin marketplace add lena-miyamoto/UtilityScripts
claude plugin install dev-utils@lena-miyamoto
```

## Skills

| Skill                        | Use                                                             |
| ---------------------------- | --------------------------------------------------------------- |
| `dev-utils:review-changeset` | Review the staged changeset; returns findings and a fix plan.   |
| `dev-utils:apply-fixes`      | Apply an approved fix plan returned by `review-changeset`.      |
| `dev-utils:optimize-repo`    | Audit and clean up instruction, skill, plugin, and agent files. |
| `dev-utils:csv-tool`         | Inspect and transform CSV/TSV files.                            |

## References

Rulebooks loaded on demand by the skills: `references/python-review.md`,
`references/model-capabilities.md`, `references/context-engineering-best-practices.md`.
