=== USER ===
# Follow-up: cross-document links

You already extracted this document. A deterministic pre-scan found wording in the
clauses below that usually signals a cross-document link, but your extraction had no
cross_reference row of the matching kind citing them.

{{doc_header}}

# Other documents in the bundle (self-descriptions only)

{{registry}}

# Uncovered clauses

{{gaps}}

{{document}}

# Task

Return {"fields": [...], "issues": [...]} for these clauses only:
- `fields`: only field_type "cross_reference" rows, one per link or amendment operation,
  each citing its clause with a verbatim quote and filling from_doc / to_doc /
  to_doc_resolved / target_clause / operation / new_text / old_value / new_value /
  controlling_doc / subordinate_doc / scope as the text states them.
- `issues`: one issue for any listed clause that is not actually such a link, saying why.
Same hard rules as before: verbatim quotes, nothing inferred, no computed dates.
