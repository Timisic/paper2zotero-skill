# Paper summary — template version 3

Write a useful Chinese summary of **about 1,000 characters**. Roughly 800–1,200 is a guide, not a quota to count against; follow a different user request. Explain the paper clearly and add one or two useful insights, rather than producing a miniature peer review.

## Read, write, check once

Read the main text, focusing on question, method, results and discussion. References, appendices and the original PDF are for questions that actually affect the summary. An abstract alone is insufficient. When a table is unclear, check the relevant part or omit the number; do not reconstruct every table or inspect every PDF page.

Use a few natural headings or paragraphs:

- **Question and approach:** the problem, design/sample and key comparison. Keep a model benchmark distinct from a clinical or user study.
- **Main findings:** two or three central results, with only the numbers needed to understand them, plus the most important limitation. No exhaustive statistics or caveat list.
- **My takeaway:** one or two paper-specific insights, connecting a finding to its interpretation and practical value or a new question. Clearly mark your inference. A full experimental proposal, falsification plan or cross-paper synthesis is optional, not a required slot.

Add a few real section/table locations where useful. Write the body draft, then read it once against the relevant source passages before creating the final summary artifact:

- For each key number, check what was measured, its denominator and time window. A total across a study is not the cost of completing one task; two separate outcomes do not establish an efficiency or causal result. Keep descriptive differences distinct from statistical tests and coded items distinct from people.
- For each takeaway, distinguish the observed result from your inference. Outcomes the paper never measured belong in a question or explicitly untested hypothesis, not a sentence saying the study demonstrates them. When a test finds no significant difference, say exactly that; it does not establish equivalence or that bias has been eliminated.

Correct only the concrete errors found in that read-back, then package and record the summary. This is the existing self-check, not another review round, character quota or report. Briefly note source inconsistencies; preserve existing summaries unless asked to replace them.

## Save and continue

For a batch, open `summary_batch_file`. Its `reading` outline gives the Markdown section lines and the end of the main text; appendices and references remain in the original source for specific checks. Write each summary body to its `content_file`, then run:

```bash
python "$SKILL_DIR/scripts/summary_artifact.py" --batch-file <summary_batch_file> --provider <actual-agent-model>
```

This validates selection and unchanged full-text hashes before saving, records all summaries under one short run lock, preserves differing existing summaries, and returns the original `resume_command` with collection/storage options. An identical retry does not rewind delivered papers. A missing body or changed source fails before saving summaries. The handoff stays in the run, so interruption needs no reconstructed paths or per-paper registration commands.

The single-paper entry remains available for an individual correction or a PDF-based summary when the chosen reading basis differs from the handoff:

Use the paths and source basis from `pending_summaries`. Save a body file and run:

```bash
python "$SKILL_DIR/scripts/summary_artifact.py" \
  --content-file <body.md> --output <paper-dir>/summary.md \
  --provider <actual-agent-model> --template-version 3 --source-basis markdown
python "$SKILL_DIR/scripts/workflow.py" record-paper --run-dir <run_dir> \
  --id '<candidate-id>' --state summary_generated --artifact summary=<paper-dir>/summary.md
```

Use `source-basis=pdf` when the readable PDF was the source. Once the selected summaries are ready, execute the returned `resume_command` (or `resume_shell`) once. It carries the approved collection and storage path into `--stages ingest`; a manually composed command must include those options until the first ingestion saves the collection. Built-in read-back is normal verification; an extra replay is a test/recovery action, not a delivery requirement.
