# Third-party skills

These folders are copied unmodified from their upstream repositories. Only a `LICENSE` file, the upstream repository's root license, was added to each. Report problems with their content upstream. To update one, copy the folder again from a newer commit and change the commit below.

## academic-paper

- Upstream: https://github.com/Imbad0202/academic-research-skills
- Path: `academic-paper/`
- Commit: `a1687d54d35f30953c2dd06065d46a89ec7e9a49`
- License: CC BY-NC 4.0, copyright Cheng-I Wu. See `academic-paper/LICENSE`. **Non-commercial use only.**
- Copied unmodified.
- Used here for literature review writing, through its `lit-review` mode.

Known limits. Upstream, this skill links files outside its own folder: the repository's `shared/`, `scripts/` and `docs/`, and the sibling skills `academic-pipeline/`, `academic-paper-reviewer/` and `deep-research/`. None of these are copied. The bilingual abstract (`../../shared/output_language_pair.md`), AI disclosure (`../../scripts/check_policy_anchor_protocol.py`, `../docs/design/...`), revision patch and full-pipeline features rely on them most.

The `lit-review` mode is not fully self-contained. It runs `intake_agent` and then `literature_strategist_agent`. On every run, the per-source "Method weaknesses" checklist in `agents/literature_strategist_agent.md` reads its criteria from `academic-paper-reviewer/references/review_criteria_framework.md` §2, which is missing here. These optional paths also name missing files:

- style calibration (`shared/style_calibration_protocol.md`)
- a venue or format profile (`shared/contracts/submission/`)
- a deep-research handoff
- a Material Passport corpus (`academic-pipeline/references/literature_corpus_consumers.md`)
- the review-form note ledger (`scripts/run_ledger.py`), used only with a passport file

The rules that matter at run time are written out in the agent files themselves. The annotated bibliography and synthesis still come out, but without the reviewer checklist.

## nature-writing

- Upstream: https://github.com/yuan1z0825/nature-skills
- Path: `skills/nature-writing/`
- Commit: `d774add241c65e89ed17a4da573b472b0972fd42`
- License: Apache-2.0. See `nature-writing/LICENSE`.
- Copied unmodified.
- Used here for introduction writing, through its `intro` section.

Known limits. It reads shared guidance from the sibling folder `../nature-shared/`, for example `../nature-shared/core/nature-introduction.md`, so both are installed side by side. It hands other tasks to Nature skills that are not included here (`nature-polishing`, `nature-response`, `nature-figure`, `nature-reviewer`).

## nature-shared

- Upstream: https://github.com/yuan1z0825/nature-skills
- Path: `skills/nature-shared/`
- Commit: `d774add241c65e89ed17a4da573b472b0972fd42`
- License: Apache-2.0. See `nature-shared/LICENSE`.
- Copied unmodified.
- A reference package for `nature-writing`. It is not a workflow to call on its own.
