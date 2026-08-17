# Historical scripts

These scripts are retained as implementation history, not supported project
commands. They are excluded from `scripts/dev.py describe` and normal agent
workflows.

Documents may reference these paths when describing historical work. Keep such
references when they provide provenance; a documentation link alone is neither
evidence that a script is active nor a reason to remove the link.

- `file_issues.py` created the original GitHub issue set from
  `docs/issues-draft.md`.
- `sync_issue_labels.py` reconciled labels from that same draft.

The draft no longer exists and GitHub is now the durable issue source, so both
scripts fail in a current checkout. They remain here only in case their parsing
or label definitions are useful when reading project history.
