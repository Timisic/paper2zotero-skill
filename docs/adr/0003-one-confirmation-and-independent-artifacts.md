# ADR-0003: One confirmation and independently deliverable artifacts

Status: Accepted.

Repeated approvals and all-or-nothing processing made ordinary literature tasks slow and caused usable work to be withheld when one artifact was missing.

The normal flow presents one candidate list and asks together for the paper selection, target collection and permission to upload full text to MinerU. Existing explicit authorization is reused within its scope. New papers or a changed upload destination require the relevant new decision.

`process_run.py` composes acquisition, verification, conversion and ingestion around one resumable run. The Agent handles screening and full-text summaries. An `awaiting_summaries` result is an internal handoff; recovery continues the same run and preserves its approval and write journals.

A verified PDF, derived Markdown and a summary can arrive separately. Missing artifacts yield `partial`; verified cloud content awaiting local attachment files yields `sync_pending`. Neither is a reason to repeat completed writes. Complete delivery still requires the corresponding artifact and read-back evidence.

Discovery has a shared budget across sources and retries. A short, supported list is preferable to padding; source failure is reported separately from an empty search result. Preflight checks only what the requested stage uses. The detailed states and commands live in [workflow.md](../../paper-to-zotero/references/workflow.md).
