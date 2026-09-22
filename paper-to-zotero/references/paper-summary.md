# Paper analysis — template version 4

Read the verified full text and produce a structured Markdown analysis from first principles: reconstruct the problem, assumptions, mechanisms and evidence. Write in the paper's main language unless the user requests another language; use the full text to resolve missing or incorrect language metadata. Keep the headings below. There is no word or character limit: use the detail needed to explain the argument, without greetings, praise or repeated conclusions.

## Read and ground the analysis

Read the main text, including methods, results and discussion. Consult a figure, table, appendix or cited source when it changes a substantive conclusion. An abstract is insufficient. Cite section, page, figure or table locations for central claims. Separate the authors' stated reasoning and measured findings from your reconstruction and proposed research directions. If the paper does not report its inspiration, identify a plausible reconstruction explicitly; do not present it as the authors' actual discovery history.

## Output structure

### 1. Task

Define the problem as precisely as the evidence permits: inputs, outputs or decisions, target outcome/objective, constraints and assumptions. For an intervention study, specify population, intervention, comparator, outcomes and the effect being estimated. Use notation or equations where they clarify the task; do not invent an optimization objective or causal model the study never establishes.

### 2. Challenge

Explain what earlier approaches do and where they fail under this task's assumptions. Connect each difficulty to a mechanism, resource constraint, information gap or empirical finding. Distinguish limitations demonstrated by the paper from limitations merely asserted by its authors.

### 3. Insight & Inspiration

Identify the observations, theories, prior work, analogies or basic principles that motivate the approach. Label inspirations and insights so their connections can be traced. For each insight, state what the authors realized, the aspect of the problem it changes, which inspiration supports it, and why that connection addresses a challenge. Distinguish an explanatory insight from the implementation that realizes it. Mark unreported inspiration as unknown or as your reconstruction.

### 4. Novelty

Explain the specific architectural, methodological or strategic contribution relative to the cited baselines. For every novelty, use this exact three-block structure, filling the blocks in the note's language and retaining the brackets and arrows:

`【problem addressed】 -> 【inspiring insight】 -> 【concrete design of the innovation】`

Make the design operational: describe the relevant components, procedure, representation, objective, interaction or intervention strategy. Link the insight to section 3. Follow the chain with the supporting evaluation and central result, including its comparison and scope. Distinguish a proposed design, an ablation-supported contribution and a demonstrated outcome. If the contribution is empirical evidence or a design finding rather than a new architecture, describe it as such.

### 5. Potential flaw

Analyze three questions:

- **Scope:** Which assumptions or contextual boundaries constrain the result? What would change with more dimensions, conditions, actors or constraints, and what extension might address that setting?
- **Data and evidence:** Which relevant data properties could make the method struggle—such as noise, missingness, selection bias, scarcity, distribution shift or unreliable measurement? Explain the failure mechanism for this paper rather than listing generic risks. For non-data-driven work, examine the corresponding assumptions or evaluation evidence.
- **Research opportunity:** Which of these difficulties is most worth investigating as a paper, and why? Formulate a testable question, explain its significance, and identify the evidence or comparison needed. Distinguish a substantive research gap from an engineering fix. Treat publishability and the proposed solution as hypotheses, not established novelty or success.

### 6. Motivation

Reconstruct the shortest defensible route from the task's basic requirements to the general idea, preferably as questions: “Earlier methods assume/do X; the essential requirement is Y; could we instead try Z?” Explain why Z is a reasonable, simple response to the challenge and which assumption it changes. This is a first-principles reconstruction, not a claim about the authors' private thought process.

## Self-check once

Check the draft against the relevant source passages before saving:

- All six sections are substantive; each novelty maps a concrete problem to an insight and a specific design.
- Key numbers retain their measure, denominator, comparison and time window. Association is not causation, a non-significant test is not equivalence, and performance while using a tool is not proof of lasting independent skill.
- Inspirations, limitations and research proposals are labeled according to their evidence. Note material source inconsistencies; leave missing evidence missing.

Correct concrete errors, then package and record the note. Completion depends on coverage and grounding, not length. Preserve existing notes unless the user requests replacement; old template versions remain readable and are not automatically regenerated.

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
  --provider <actual-agent-model> --template-version 4 --source-basis markdown
python "$SKILL_DIR/scripts/workflow.py" record-paper --run-dir <run_dir> \
  --id '<candidate-id>' --state summary_generated --artifact summary=<paper-dir>/summary.md
```

Use `source-basis=pdf` when the readable PDF was the source. Once the selected summaries are ready, execute the returned `resume_command` (or `resume_shell`) once. It carries the approved collection and storage path into `--stages ingest`; a manually composed command must include those options until the first ingestion saves the collection. Built-in read-back is normal verification; an extra replay is a test/recovery action, not a delivery requirement.
