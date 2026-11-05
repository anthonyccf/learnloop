# Code Analysis ingestion fix and live validation

Completed 21 October 2026, using the configured real model, embedding service, Qdrant, PostgreSQL, API and frontend proxy.

## Scope and reset

The failed upload was `04_Code Analysis_2026-27.pdf` in the Malware course, document `0c8d9db3-1342-4742-a615-651bbccf9491`. Its generated graph, extraction checkpoints, SQL passages and document-scoped retrieval points were cleared and rebuilt from the original uploaded PDF. The PDF itself was preserved. No activities referenced its old concepts.

The other document, `06_Reversing - Crash course in CISC_2026-27.pdf`, has existing learner activity and was preserved. Hash comparisons confirmed unchanged document graph/resources, learner evidence/version, sessions, activities and submissions.

Before-state backups, including the original PDF and generated state, are under `E:/agentic-learning/tmp/code-analysis-reingest/`. The original failed state is in `20261021T084808Z/before.json`. Three superseded failed preparation runs were separately archived to `retired-run-history.json` and removed from the application's run list after successful acceptance checks. The final successful run remains available.

## Fixes

- Related links are treated as undirected pairs. Exact/reversed duplicates and redundant overlaps with accepted prerequisites are removed deterministically. Unknown concepts, self-links, cycles and invalid prerequisite evidence still fail validation.
- Relationship errors identify the offending pair. A bounded history of failed drafts is retained privately. A failed review preserves topic grouping and analyst output; retry reruns the invalid stage and receives validation feedback.
- Live testing also exposed source-grounding failures: generated details exceeded the cited evidence, and some drafts used incorrect passage IDs. Expert prompts now use short passage aliases that are translated back to real IDs before persistence; concept IDs and source text are not rewritten.
- Rejected section/material drafts receive grounding findings for at most two corrective regenerations. Every revision must pass source validation and a fresh grounding review. Exhaustion still stops for review. Private failure diagnostics retain the review findings without exposing test keys in public responses.

The first two live trials stopped safely at grounding gates. They were not counted as successful ingestion. After the corrections, preparation was restarted from the original PDF with cleared generated content and completed in one worker attempt.

## Successful live run

Run: `3e4a1119-6a0a-45d5-ad11-95245a501aa0`

| Check | Result |
| --- | --- |
| Run status | Completed, no error |
| PDF pages | 48 |
| Extracted passages reviewed | 47 of 47 |
| Sections reviewed | 6 of 6 |
| Accepted concepts from this PDF | 22 |
| Reviewed lesson packs | 22 of 22 |
| Private test questions | 44 |
| Public lessons returned for this document | 22 |
| Course-wide organized concepts | 59 across the two documents |
| Course-wide topics / prerequisites / related links | 11 / 29 / 25 |
| Structural and source-reference checks | Passed |
| Grounding receipts for all saved packs | Current and supported |
| Scoped vector retrieval | 5 matching passages, all from this document |
| Answer-key privacy | No private question keys in the public materials response |
| Existing course/learner data | Preservation hashes matched |
| API after restart | Healthy |
| Frontend backend proxy | All 22 lessons accessible through port 3100 |
| Superseded failed preparation entries | 3 archived and removed |

The successful model review returned valid related links without requiring duplicate/overlap removal. Regression tests separately verify deterministic normalization and preservation of strict rejection rules.

## Regression verification and service state

All **84 backend tests passed**, including isolated PostgreSQL integration tests. Changed Python modules pass Ruff lint and formatting checks. One existing Starlette/AnyIO deprecation warning remains.

The API and normal durable worker were restarted with the updated code. The final live audit is saved in `E:/agentic-learning/tmp/code-analysis-reingest/report.json`. Completed preparation was verified through the API and the frontend proxy after restart.

Passage coverage and model grounding approvals are checks on the implemented ingestion workflow; they do not establish complete pedagogical coverage or human learning effectiveness. This test reprocessed the failed Code Analysis PDF, not the other document's historical teaching packs.
