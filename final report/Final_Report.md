# [Group 72] LearnLoop: A Stateful Agentic Platform for Adaptive Learning

**Course:** COMP7608B Large Language Models — Final Project Report  
**Deadline:** 25 November 2026

| Email |
| :--- |
| u3529946@connect.hku.hk |
| u3528357@connect.hku.hk |
| u3665708@connect.hku.hk |
| u3679169@connect.hku.hk |

**Submitted version:** `[TEAM TODO: git tag or commit, for example v1.0-final]`  
**Repository:** `[TEAM TODO: link, if the repository is shared. The submission ZIP includes the source snapshot.]`

---

## Summary

This report describes LearnLoop, a local learning system for a university student who studies from their own lecture files. The student uploads a readable PDF or text file. The system builds a map of concepts and prerequisites, then assigns one checked question at a time. The result of each answer is saved, so a later session continues from the same record.

Three agents share this loop. The Expert builds the course: concepts, prerequisite links, a short lesson, and checked starter questions. The Tutor reads the saved record and selects the next activity that the prerequisite rules allow. The Reviewer marks the answer against a private key and writes feedback. The language models propose and explain. Fixed Python rules decide what may be published and what may count as understood. A hint, a single correct answer, or an uncertain answer does not establish mastery.

The delivered system is a web application: a FastAPI backend, a separate background worker, a Next.js frontend, and one SQLite database with `sqlite-vec` for search. A Workbench stores prompt edits, and a separate harness runs simulated students. Section 2 explains the agent options. The application uses one of them: grounded, utility, and weighted. Across 36 completed live simulated episodes, the Tutor assigned no locked topic, repeated no question, and wrote no invalid progress update. A practice step that uses a saved question costs about US$0.0006 and requires a few seconds of model time.

---

## 1. Users and Proposal Continuity

### 1.1 Users and needs

The intended user is a university student revising a technical course from their own slides, in a subject where later topics depend on earlier ones. Four needs follow from that setting.

1. Slide order follows the lecture. The student still needs to see which ideas must come first.
2. A general chat assistant may explain an idea that is absent from the slides, or mark an answer with a key it has just written.
3. One correct choice, including a correct choice made after a hint, is often treated as evidence that the topic is understood.
4. Closing the page removes any structured record of which topics remain weak.

The student therefore needs a path through their own material, practice matched to the current record, feedback tied to the source pages, and a record that remains available in the next session.

### 1.2 Requirements and scope

For one course unit of about 5–20 concepts, the prototype has five requirements.

1. Accept a readable PDF or text file of at most 20 MB and 200 pages, and attach every concept, link, lesson, and question to a page in that file.
2. Withhold a quiz on a topic until every direct prerequisite is currently demonstrated at the required level.
3. Mark a topic as demonstrated only after two separate, unhinted, rubric-meeting answers at the target difficulty. Schedule a review after 7 days. After a topic has been demonstrated, two clear failures in a row mark a confirmed weakness.
4. Keep answer keys and rubrics on the server until the student submits an answer.
5. Resume an interrupted upload or a crashed worker, and count a repeated submission only once.

The submitted system is a local prototype for one person on one machine. Shared class accounts, missions and rewards, web search, and optical character recognition for scanned handwriting lie outside the delivered scope. When Poppler is installed, an optional vision model can read figures on slides.

### 1.3 Planned work and delivered work

Table 1 compares the proposal with the submitted system.

| Proposal item | Status | Delivered form |
| :--- | :--- | :--- |
| Three agents in one prepare–practise–assess loop | Delivered | The Expert, Tutor, and Reviewer each have a separate package and job type. |
| A source-checked concept map with three difficulty levels | Delivered, with a smaller starter set | Each concept receives one lesson and two checked Basic questions at setup. Harder questions are written when the Tutor needs them. |
| Ranked Tutor actions and saved plan versions | Delivered | The program scores the allowed options. The model selects one of the top 12 and gives a reason. Each plan revision is saved. |
| Rubric feedback, misconceptions, timing, and contradictions | Delivered, and extended | Answers may be one choice, several choices, a filled blank, or a short written answer. |
| A learner record with an explicit weakness rule | Delivered | The rule is in `core/domain.py`. Confirmed weakness requires two failures. |
| A published, versioned course | Delivered | A session remains pinned to the release on which it started. A later rebuild leaves that session unchanged. |
| A prompt workbench | Added after the proposal | The Workbench stores prompt versions, selects Expert prompt styles, and lets a person approve a lesson that the automatic check held back. |
| LangGraph | Changed | The runtime is a Python dispatcher with SQL job leases and checkpoints (`runtime/workflows.py`). Learner updates already commit in one database transaction, so the job state uses the same database. |
| PostgreSQL, Qdrant, and Docker | Changed | The default store is SQLite with `sqlite-vec`, so the stack runs with Python and npm. The earlier database adapters remain in the code. |
| Token, cost, and latency records | Delivered for preparation, the Workbench, and evaluation | Those runs keep a record of each call. An ordinary practice step has a timeout and a token cap. It has no running dollar budget. |
| 27 prompt combinations, four simulated students, and two baselines | Harness delivered; full paid study not run | Section 2 defines nine emphases. The application uses one combination. Offline, 216 study episodes and 24 baseline episodes completed. Live runs use the same combination. See Section 5. |
| Many learners on one shared course, plus missions and rewards | Not delivered | The implemented work concentrates on source checks, grading, and saved progress. |

The project aim remains a stateful learning agent over a student’s own course files. The changes concern how the application is run and how much of the planned study was executed. `[TEAM TODO: state whether the teaching team was notified of any change. If no notice was required, retain this paragraph.]`

---

## 2. Design and Implementation

### 2.1 Workflow

The page and the model calls are separate. The page sends requests to FastAPI. Long jobs wait in SQLite until a background worker takes them. Only the worker calls the language model. The page receives no answer key before the student submits.

```
Student page  ->  API checks  ->  job in SQLite  ->  worker
                                      ^              |
                                      |              +-> Expert, Tutor, or Reviewer
                                      |                     |
                                      +---- saved result ---+
                                                    |
                              OpenRouter (gpt-6-luna) and local Ollama (bge-m3)
```

*Figure 1. Request path. Answer keys remain on the server until assessment.*

**Preparation.** The student uploads a file. The worker splits it into overlapping passages of about 1,600 characters and keeps the page number (`core/domain.py`). Local `bge-m3` embeddings are stored in `sqlite-vec`. The Expert reads every section and proposes concepts with citations. Concepts that repeat across files are merged. A relationship analyst proposes links. A separate reviewer may keep a link, mark it as related, or remove it. The reviewer adds no new prerequisite. A graph with a cycle or an unknown identifier is rejected. Each concept is placed in a basic, intermediate, or advanced layer, with a short statement of what the lesson teaches and what it assumes. The Expert then writes the lesson and two Basic questions. A fresh model call solves each question from the cited pages and does not see the proposed key. A rejected draft may be repaired twice, with a wider set of pages on each attempt. A draft that still fails is held for a person (`manual_review.py`). A draft that passes is published as one fixed course release.

**Planning.** The session is pinned to that release. `core/planning.py` removes any topic whose prerequisites are not demonstrated, then scores the remaining topics. Need, uncertainty, review urgency, a recent miss, and a match to the student’s goal raise the score. The Tutor receives at most 12 options and must return one of those identifiers, together with a short reason for the student. An unused checked question at the required level is assigned when one exists. When the bank has none, the Tutor asks the Expert for a new question, and that question passes the same checks.

**Assessment.** The server compares a selected option or a filled blank with the private key. The Reviewer scores each rubric point, may quote the student’s own words, and may mark the answer as uncertain or in tension with an earlier answer. A quote that is absent from the answer is rejected. Written reasoning may lower a score. It does not turn a wrong choice into full credit. `assess_evidence()` then updates the learner record. The mark, the new record, and the activity event are saved in one transaction. The page remains on the feedback until the student requests the next activity.

**Continuation.** Tutor chat while a question is still open counts as a hint. Chat after submission leaves the evidence unchanged. The next plan is built from the saved record.

### 2.2 Architecture options and rationale

LearnLoop must prepare course material, select an activity, assess an answer, and retain progress across sessions. The team considered options for organizing the agents, controlling their actions, assigning decision authority, and storing memory. The selected architecture combines three specialized agents, Tutor-led learning orchestration, a controlled workflow, program rules, and persistent learner state.

**One agent or specialized agents.** A single general-purpose agent could read the lecture, choose activities, and mark answers. It would be simpler to orchestrate and could maintain a continuous conversation. However, it would need access to source material, learner history, and answer keys at different stages. Keeping those inputs separate would depend heavily on its instructions.

LearnLoop instead separates the Expert, Tutor, and Reviewer. The Expert prepares course material, the Tutor selects an activity using the learner record, and the Reviewer assesses a submitted answer using the private key and rubric. Each role receives the information needed for its task, and its output can be inspected separately. This separation requires more orchestration and may require more model calls. It also does not guarantee independent judgments: separate calls may use the same model and share its errors. For question checking, a fresh call solves the item without seeing the proposed key.

**Autonomous agent or controlled workflow.** An autonomous tool-using agent could decide which tools to call and in what order. This would offer flexibility for unexpected requests, but the application would have less predictable control over whether a required check was performed or a prerequisite was respected. LearnLoop uses a controlled workflow: a Python dispatcher invokes the appropriate agent step, validates its result, and saves the outcome. SQL jobs and checkpoints support recovery after interruption. The trade-off is that new behaviours require changes to the workflow rather than being discovered by an open-ended agent.

**Orchestration: peer agents, a supervisor, or the Tutor.** Peer-to-peer agents could delegate to one another flexibly, but their interaction paths would be harder to trace. A separate supervisor agent could route work among specialists, at the cost of another model decision and a potential routing error. A fully fixed pipeline would be easier to trace, but less able to adapt its activity selection to the learner's record.

LearnLoop instead uses the Tutor as the learning orchestrator. The Tutor selects the next activity from the eligible candidates and coordinates question preparation. If no suitable checked question is available, the Tutor workflow requests one from the Expert. This places the activity decision with the agent responsible for the student's learning plan. After submission, a separate assessment workflow invokes the Reviewer and saves the resulting evidence; the Tutor uses the updated record when building the next plan. The Tutor does not independently invoke the Reviewer or control every agent interaction.

The Tutor's orchestration is bounded by application code. The Python worker dispatches jobs and executes workflow steps; program rules calculate eligibility, validate the selected candidate, and manage persistence and recovery. This division supports adaptive activity selection while keeping prerequisite checks and state updates consistent. Its trade-off is that new coordination paths must be implemented in code, and the Tutor's choice is limited to the offered candidates.

**Model-led decisions or model assistance with rules.** A model could choose any next topic and decide directly whether an answer demonstrates mastery. It could consider nuanced language, but its decisions might vary across calls and could conflict with the requirement that one correct or hinted answer must not establish mastery. In LearnLoop, models extract and explain concepts, select from eligible activities, and assess written reasoning against a rubric. Program rules determine eligibility and update the learner record. The Tutor therefore chooses from a computed list rather than the entire course. This makes the rules testable, although their thresholds are set by the team rather than learned from student data. Validation also cannot guarantee that every generated lesson or grading judgment is correct.

**Conversation history or structured memory.** Conversation history can preserve the context of a short tutoring interaction, but a model would have to reconstruct progress from a growing transcript in each later session. LearnLoop stores a structured record for each topic and difficulty, alongside answers, plans, and activity events. A later session can use the saved state directly. This requires explicit update rules and may omit aspects of understanding that do not fit the record.

The final architecture prioritizes traceability, prerequisite enforcement, and recovery for a local single-user prototype. These are design choices, not an experimentally established ranking of architectures. The offline study checks that the prompt combinations execute, and the live runs use only the selected setup. A controlled architecture comparison would need the same course material and task conditions, together with measures of grounding, assessment quality, learning outcomes, latency, and cost.

### 2.3 Prompt options and the selected setup

Each agent also has three prompt emphases. The output schema, the source checks, and the progress rules stay fixed. Only one added instruction changes. The 3 × 3 × 3 combinations form 27 study cells, defined in `learnloop/evaluation/variants.py`.

| Agent | Option | Instruction |
| :--- | :--- | :--- |
| Expert | structural | Produce a clear concept map and complete every requested field. |
| Expert | grounded | Attach a citation and a stated scope to every field. |
| Expert | verified | Check arithmetic, level, and prerequisite consistency before returning the reply. |
| Tutor | state | Prefer the current estimate and the latest answers. |
| Tutor | graph | Prefer prerequisite order and a connected path. |
| Tutor | utility | Use the scores already computed for need, uncertainty, review urgency, recent performance, and the student’s goal. |
| Reviewer | correctness | Follow the key and the rubric, and do not infer reasoning the student did not write. |
| Reviewer | weighted | Follow the key, and also use hints, earlier attempts, time taken, and contradictions. |
| Reviewer | conservative | Mark uncertainty when the writing is thin or conflicts with an earlier answer, and avoid a confident claim. |

The application uses grounded, utility, and weighted.

Grounded follows the requirement that a lesson or question cite the uploaded pages. Structural places more emphasis on map organization than on citations. Verified asks the generating model to check its own draft. The system already runs that check in a separate call that does not see the key.

Utility follows the menu the Tutor receives. Every option arrives with a score. The state emphasis prioritizes the learner record, while the graph emphasis prioritizes prerequisite order. Either could place less emphasis on other factors included in the computed score.

Weighted follows the feedback the student should receive. A hint, a long response time, or a clash with an earlier answer belongs in the comment. None of these signals changes a wrong key. Correctness places more emphasis on the key and rubric than on that history. Conservative places more emphasis on withholding confident claims when the writing is ambiguous. These are differences in instruction, not measured differences in feedback quality.

This selection is a design decision. An offline run executed all 27 cells with scripted answers, which shows that every cell can run. That run does not rank the cells. The earlier live episodes in Section 5.4 use this one cell. Section 5.3 records a separate live grid over the three Expert prompt styles and the saved Tutor and Assessing templates. That grid was still running when this report was updated, and it does not select a cell by score.

The Expert’s course-building prompts have a second setting, `ORGANIZATION_PROMPT_VARIANT`, in `agents/expert/prompts_variants.py`. All four styles return the same kind of JSON. They differ in the form of the instructions.

| Style | Form of the instructions | Use |
| :--- | :--- | :--- |
| baseline | The production prompt in `agents/expert/prompts.py`. | Default for uploads and for the live runs. |
| rules | Labelled constraints, followed by a short self-check. | Workbench and evaluation. |
| procedural | Numbered steps, with a test at each step. | Workbench and evaluation. |
| exemplar | The same rules, taught with examples from introductory statistics, so the examples do not copy the lecture under test. | Workbench and evaluation. |

Baseline is the default because the other three styles are prepared for a controlled comparison of prompting style. First-stage live preparation runs across all four styles on `COMP7608B_Lec08.pdf` are recorded in Section 5.3; human audit of their concepts and prerequisite links remains pending. Selecting another style in the Workbench leaves the validators unchanged.

The choice of agent setup is separate from the choice of the next question. During a session, the program builds the allowed list, and the Tutor returns one identifier from that list. Any other identifier stops the run with `invalid_plan`.

### 2.4 Decisions and limits

| Decision | Agent | Stopping rule |
| :--- | :--- | :--- |
| Which ideas a section teaches | Expert | A citation does not resolve, or two repairs leave the draft unsupported. |
| Which links are prerequisites | Expert analyst, then reviewer | The reviewer adds a link the analyst did not propose, or the graph contains a cycle. |
| Whether a drafted question is sound | A second Expert call | The solver and the proposed key disagree, and repair does not remove the disagreement. The item stays unpublished. |
| The next topic, action, and level | Tutor | The returned identifier is absent from the offered list, or a prerequisite changes before the save. |
| A new question when the bank is empty | Tutor, then Expert | Generation fails. The Tutor may then use a saved question when one exists. |
| Feedback, a misconception quote, and uncertainty | Reviewer | The quote is absent from the student’s text, or a hinted, partial, or uncertain answer is treated as mastery. |
| Whether work continues | Worker | The API key is missing, so the run pauses before any model call. The student may also stop a run. Completed sections remain saved. |

### 2.5 Learner record

Each topic keeps a separate record at basic, intermediate, and advanced. The topic as a whole is judged at its target level, which is intermediate unless the curriculum sets another level.

A topic begins unassessed. The first sound answer, and also any wrong, hinted, or uncertain answer, moves it to developing. A second, different, unhinted answer that meets the rubric moves it to demonstrated, and a review is set for seven days later. On that date the topic is due for review. One miss then is recorded as a contradiction and schedules review. Two unhinted misses in a row confirm a weakness and return the level to developing. Recovery from a confirmed weakness requires two new unhinted answers. Success at basic level does not unlock a topic whose target is intermediate.

After a miss, a hint, or an uncertain answer, the next question moves down one level. It moves back up only after the lower level is demonstrated.

### 2.6 Models, prompts, tools, and state

Generation uses `openai/gpt-6-luna` through OpenRouter. A second model may be set for verification, and another for slide images. Embeddings remain local: Ollama serves BAAI `bge-m3` with 1,024 dimensions. Evaluation runs use temperature 0.2 and a recorded seed. Each request times out after 90 seconds, and at most eight model calls run at once.

Each agent has its own prompt file. The active built-in set is version `v2`. The Workbench can store a further copy of a prompt. Every model reply must match a Pydantic schema.

The model has no open tool loop and no permission to write SQL. The worker calls a fixed set of steps, and each step is written to the activity trace: retrieve passages, review sources, publish, choose an activity, request an Expert question, mark an answer, update evidence, and revise the plan.

SQLite is the only store in the default setup. Course releases are fixed and hashed. Sessions, answers, plans, jobs, and learner records are stored separately. A question row has a public part, containing the stem, the choices, and the page, and a private part, containing the key, the rubric, and the explanation.

### 2.7 Design choices

Five choices shape the prototype.

1. Progress rules are written in code, so they can be tested. The thresholds of two successes, two failures, and seven days are set by hand. They are not estimated from student data.
2. Reading every section of an upload retains definitions that a short search can miss. Preparation of a unit with 5–7 concepts then takes about 3–11 minutes.
3. Writing only Basic questions at setup reduces the initial cost. The first Intermediate or Advanced question takes about 4–14 seconds while the Expert writes and checks it.
4. The Tutor selects from at most 12 allowed actions. In the recorded runs this produced no invented topics and no prerequisite violations.
5. SQLite with a file lock supports one local user and a simple setup. It is a weak fit for many students writing at the same time.

### 2.8 Task traces

The course asks for an ordinary task, a changed request, and a failure. The three traces below are taken from saved runs and from the code paths that enforce them.

**Ordinary task.** In live episode `2eaf22b3eaac07c3` (run `0a0e83f0`), the simulated student studies two ideas from the language-model slides: paged key-value storage (`c01`) and mixture-of-experts parameters (`c02`). The pre-test on `c01` was incorrect, so both topics are developing.

1. `core/planning.py` scores “practise c01 at basic” and “practise c02 at basic” equally, at 4.0.
2. The Tutor (`choose_candidate`, about 3.2 s) selects c01 and assigns saved question `c01|0`. The key remains on the server.
3. The answer is incorrect. `assess_evidence()` records the miss and leaves c01 at developing. The topic was never demonstrated, so one miss does not confirm a weakness.
4. On the next plan, the recent miss raises c01 to 5.0 under the action “remediate,” above c02 at 4.0. The Tutor (about 2.2 s) assigns a different checked question, `c01|1`.
5. The student selects the correct option and writes: “It includes scheduling and kernels, so it does not isolate PagedAttention’s contribution.” The Reviewer (about 3.8 s) gives that rubric point full marks and quotes the sentence exactly. The record then contains one qualifying answer. The topic remains developing, because demonstration requires two.

**Changed request.** A question on topic A is still open, and the student asks to move to topic C, with the chain A → B → C. B is unassessed, and A is developing. `prerequisite_block()` in `core/domain.py` walks back through unmet parents until it finds a topic that can be started, which is A. The API returns HTTP 409 with code `unmet_prerequisites`, names B as the missing prerequisite, and offers practice on A. The open question and the learner record stay unchanged.

**Failure.** During preparation, a slide names a benchmark and does not explain it. The Expert drafts a claim or a key that the source check or the blind solver rejects (`agents/grounding.py`). The pack is not saved as teaching material. The Expert may try twice more, using 6, then 12, then 18 passages. If the draft still fails, it is stored privately, and the review screen shows the problem without the key (`manual_review.py`). A person may regenerate it or approve it by name. Publication without that step is refused. The case is covered by `test_existing_failed_pack_is_repaired_or_remains_withheld`.

---

## 3. Reliability and Recovery

Failure behaviour was tested with stand-in model clients on temporary databases, and several failures also occurred in live runs.

| Failure | Detection | Response | Message to the user | Evidence |
| :--- | :--- | :--- | :--- | :--- |
| The provider times out or returns a server error during preparation | HTTP 408, 425, 429, or 5xx, or the 90-second timeout | The client retries transient errors up to 3 times. The worker allows 4 attempts, with 20 seconds between them. Finished sections are kept. | “Processing was interrupted. Retrying automatically in 20 seconds.” or a Retry button | `test_section_review_resume_only_reprocesses_failed_section` |
| A generated lesson or question is unsupported | Unknown page identifier, a failed source review, or a key the solver rejects | Two repairs, then the item is held for review | The review screen lists the gap and hides the key | `test_semantic_failure_blocks_graph_publication` |
| The same answer is sent twice, or the page shows an old learner version | Matching `operationId`, or `expectedLearnerVersion` | The same operation returns the original receipt. A clash or a stale version returns 409. | The page reloads. The answer is counted once. | `test_assessment_waits_for_explicit_next_and_retry_keeps_evidence_once` |
| The process stops while saving a mark | The database transaction does not commit | The mark, the learner version, and the event are rolled back together | The run can be retried. Progress is unchanged. | `test_assessment_commit_failure_rolls_back` |
| The worker stops, or its lease expires | The operating system releases the lock file. A lease lasts 1,800 seconds. | The next worker continues the job. A second live worker does not take it. | The job continues from the last checkpoint | `test_expired_job_lease_is_reclaimed` |
| The API key is missing, or the user stops the run | Checked before any model call, and again between steps | The run pauses with no call, or stops and keeps saved work | “Configure the generation model, then resume.” or “Stopped by user. Saved work is retained.” | `runtime/workflows.py`, `runtime/worker.py` |
| A simulated episode reaches its call budget | Checked before the next call: 64 calls or 250k tokens per episode | The episode stops. The ledger up to that call is kept. | The report marks the episode `budget_exhausted` | Live run `2c9c90e9`; budget tests in the harness |

Two of these cases occurred with the live provider.

In batch `722a04b0`, with 5 concepts, three simulated students finished and the novice run stopped with a `ValueError` after 22 calls. Each student has a separate episode folder, so only the novice episode was rerun (`c01c4eef`, `1fedf3cb`). Course preparation, which had cost US$0.041, was not repeated, and the three finished episodes remained valid.

In batch `2c9c90e9`, with 7 concepts and 5 activities, three profiles finished at about US$0.011–0.012. The hint-dependent profile continued to request help until the episode reached the 64-call cap. The harness stopped before the next call and kept the ledger.

A repeated learner action is safe for the saved record and still has a provider cost. Sending the same answer again does not add a second success. Calling the provider again spends tokens. If the connection drops after OpenRouter has already run the prompt, the provider may charge for a reply that was never stored. Those calls are marked `usageMayBeIncomplete`, so the ledger does not record the cost as zero. The evaluation harness has a fixed call and token cap. The ordinary application caps each request and the number of attempts. It does not keep a dollar budget across a study session.

---

## 4. Non-Functional Requirements

The measurements below come from 18 live batches and 1,541 completed model calls. About 1,240 of those calls belong to the simulated student. The table reports LearnLoop and the simulator separately.

| Requirement | Target | Result |
| :--- | :--- | :--- |
| Practice-step latency | Median under 5 s per agent call, and 95th percentile under 10 s | Tutor: median 3.34 s, 95th percentile 5.58 s (152 calls). Reviewer: median 4.17 s, 95th percentile 8.03 s (128 calls). A saved question requires one Tutor call and one Reviewer call, about 7.5 s of model time at the median. |
| First harder question | A new checked question may be slower | Expert question calls: median 3.58 s, 95th percentile 13.85 s (21 calls). |
| Course preparation | Under 12 minutes for 5–7 concepts | 3.2–10.9 minutes (194–652 s), over 12–40 Expert calls. Workbench run `5935f369` (7 concepts) took 240 s and US$0.019. Run `722a04b0` (5 concepts) took 652 s and US$0.041. |
| Cost | Under US$0.002 per student turn, and under US$0.08 per prepared unit | One Tutor call averages US$0.00029. One Reviewer call averages US$0.00032. A saved question costs about US$0.00061. A newly written question brings the turn to about US$0.00090. Preparation of 5–7 concepts cost US$0.016–0.059. A simulated episode costs US$0.0035–0.012 because it also pays for the simulated student. |
| Workload | Oversized files fail before a model call | Limits are 20 MB, 200 pages, and 1,000 passages. The worker allows four attempts. Evaluation stops at 80 calls or 400k tokens per concept, and at 64 calls or 250k tokens per episode. |
| Privacy | Keys and credentials remain off the page | Every `/api` route requires the bearer token. Secrets are stored in `.env`. The review screen removes keys. Course text and written answers are sent to OpenRouter. Embeddings remain on Ollama. |
| Integrity | A crash or a repeated click leaves the record unchanged | Each mark uses one transaction, a version check, an operation identifier, and a hash on the course release. The automated tests and the live episodes showed no partial write and no double-counted answer. |

The operating assumptions are one local user, Ollama at `localhost:11434` with `bge-m3`, an OpenRouter key with credit, and a text PDF or a `.txt` file. A scanned page with no text layer is rejected. Optical character recognition is not included.

---

## 5. Evaluation

### 5.1 Cases and judging rules

| Case | Input | Expected outcome | Observed outcome |
| :--- | :--- | :--- | :--- |
| Representative | Upload readable notes, publish the course, answer questions, and open a new session. The live journey used synthetic gradient-descent notes. Later runs used COMP7608B Lecture 2. | Citations resolve. Keys stay hidden. The first sound answer is developing. The second is demonstrated, with review in 7 days. The new session keeps the record. | All 21 checks passed in the journey of 19 October. |
| Challenging: prerequisites | Request a topic whose parent is unassessed, developing, passed only with a hint, or passed below the target level. | HTTP 409. The open question remains. The missing parent is named, and an earlier allowed topic is suggested. | Passed in API tests. Prerequisite violations were 0 in 36 live episodes. |
| Challenging: weak evidence | Use a hint and then answer correctly. Answer the choice correctly with a weak explanation. After demonstration, miss twice. | A hint or a partial rubric does not count toward the two required answers. The first later miss schedules review. The second returns the topic to developing. | Passed in the weakness tests and in the live journey. |
| Failure | An unsupported draft, a repeated submission, a worker crash, or a simulated student that keeps requesting hints. | Hold the draft after two repairs. Count the answer once. Resume from the checkpoint. Stop at the call cap. | The withhold test passes. Run `2c9c90e9` stopped at the cap. |

### 5.2 Software tests and the live journey

The backend suite contains 311 tests. On the current working tree, 302 pass and 9 fail. An earlier failure, in which an unrepairable pack could still be published, now passes. The 9 failures are in organisation, slide-image reading, and tutor chat. They come from uncommitted work on this tree and must pass before the submission is tagged. The frontend has 44 component tests, together with type and lint checks, covering the concept map, formulas, and practice state.

On 19 October the live API, the live model, live embeddings, and the live worker were run on a disposable database (`backend/docs/learning-journey-validation.md`). All 21 checks passed. The run covered background processing, a graph of 3 concepts and 2 links, 6 private questions, reuse of a repeated upload, the prerequisite explanation, a hinted correct answer that remained assisted, demonstration only after two independent answers (learner version 4), a new question after the prepared pair was used, and the same history in a later session. The page rendered all 3 nodes and 39 formula lines. This journey shows that the loop works on a small module. It does not show that every generated lesson is factually correct.

### 5.3 Method

The harness defines four hidden profiles: novice, intermediate, misconception-prone, and hint-dependent. The Tutor and the Reviewer do not receive the hidden ability or the planted misconception.

Each episode begins with a held-out multiple-choice item for each concept at each level. Those items are excluded from teaching and do not count as demonstration. The student then completes a small number of activities. A separate post-test, scored outside the Reviewer, measures the change. An episode is excluded when the simulated replies agree with the profile’s target draws less than 75% of the time. Completed live episodes agreed 97–100% of the time.

The recorded measures are the pre-test to post-test change, agreement between LearnLoop’s learner state and the hidden state, the rate at which a topic is marked demonstrated when the post-test disagrees, misconception matches, prerequisite violations, repeated questions, tokens, cost, and latency by role.

#### First-stage comparison of Expert, Tutor, and Assessing prompts

The first-stage live Expert runs across all four styles on `COMP7608B_Lec08.pdf` have been completed (human audit of the generated graphs remains pending). The Tutor and Assessing comparison below is a separate 27-cell simulated-learner grid on three of those published generations. It is not the offline 27-cell scripted grid in Section 5.4, and it does not include the Baseline generation.

The six Tutor and Assessing templates use the built-in v2 prompts and the configured model. Their temperature is left at the provider default. Within each agent's comparison, the shared instructions and output schema stay the same; the added planning or assessment instruction changes. The Tutor templates also share the same response and question-selection instructions. The Assessing templates share the same feedback and learning-memory instructions. Program rules and validators remain unchanged. The question-selection instruction is saved in the Tutor template but does not affect Tutor runs.

| Agent | Saved template | Added emphasis |
| :--- | :--- | :--- |
| Tutor | Tutor - Learner-focused | Prioritize the learner's current state and recent answers, including a supported recent mistake, uncertainty, or weakness. |
| Tutor | Tutor - Prerequisite-focused | Prioritize a coherent path through the prerequisite graph and eligible foundations for the learner's goal. |
| Tutor | Tutor - Balanced | Consider the supplied scores and factors for need, uncertainty, review urgency, recent performance, and the learner's goal. |
| Assessing | Assessing - Correctness-focused | Award rubric points only for evidence in the answer; do not infer unwritten reasoning. |
| Assessing | Assessing - Context-aware | Apply the key and rubric while considering hints, earlier attempts, and contradictions in the feedback; do not treat response time as proof of understanding. |
| Assessing | Assessing - Conservative | Avoid unsupported inferences and identify uncertainty when an answer is ambiguous, incomplete, or inconsistent with earlier evidence. |

**Exact differences in the saved prompts.** The excerpts below reproduce the distinguishing instructions. They are instructions to the model, not measured outcomes. The Expert styles change four course-organization prompts: section concept extraction, relationship analysis, relationship review, and curriculum planning. Their full texts are in `agents/expert/prompts_variants.py`; the baseline is in `agents/expert/prompts.py`. The three saved Expert templates select their respective organization style and have no additional text in their three editable prompt fields.

| Expert setting | Exact examples of distinctive instructions |
| :--- | :--- |
| Baseline | Uses the production organization prompts in `prompts.py`, without the added labelled checklist, numbered procedure, or contrastive examples of the other styles. |
| Expert · Rules | Groups constraints under labelled rule headings (`Evidence rules`, `Granularity rules`, `Prerequisite rules`, `Scope fidelity rules`) and ends with a self-check. Defines both a teachability floor (enough evidence for a standalone short lesson, concrete example, and two basic questions) and a split ceiling, requires direct-use prerequisites (B directly uses A's definition, formula, or mechanism), and bounds `teaches` to one summary-faithful sentence. |
| Expert · Procedural | Uses numbered decision steps (`Step 1` to `Step 7`) with explicit tests: a floor-and-ceiling granularity test in concept extraction, a direct-use dependency test for candidate prerequisites, transitive pruning, and layer-ordered scope drafting with one concise summary-bounded `teaches` sentence. |
| Expert · Exemplar | Teaches decisions through contrasting good/bad examples from introductory statistics (unrelated to the evaluated lecture). Illustrates good granularity vs overly coarse, evidence-starved thin splits, synonyms, wrong-chunk attribution, mutual-pair cycles, `mean` → `variance` prerequisites vs `mean`–`median` related links, and over-claimed `teaches` scopes. |

The following are the complete variable **Learning plan** instructions saved in the Tutor templates, excluding their identical shared suffix:

**Tutor - Learner-focused**

> Choose one activity from the supplied eligible candidates. Prioritize the learner's current state and recent answers. Prefer an activity that addresses a recent mistake, uncertainty, or weak performance when the supplied record supports it. Do not invent learner history. Return the selected candidate identifier and a concise reason grounded in the record.

**Tutor - Prerequisite-focused**

> Choose one activity from the supplied eligible candidates. Prioritize a coherent path through the prerequisite graph. Prefer an activity that strengthens an eligible foundation for the learner's goal, while considering the supplied learner state. Use only the supplied graph and candidate information. Return the selected candidate identifier and a concise reason grounded in the learning path.

**Tutor - Balanced**

> Choose one activity from the supplied eligible candidates. Consider the supplied scores and factors, including learning need, uncertainty, review urgency, recent performance, and the learner's goal. Select the candidate that best addresses the overall learning need. Do not invent scores. Return the selected candidate identifier and a concise reason grounded in the supplied factors.

The following are the complete variable **Answer analysis** instructions saved in the Assessing templates, excluding their identical shared suffix:

**Assessing - Correctness-focused**

> Assess the submitted answer against the supplied answer key and rubric. Award each rubric point only when the student's answer provides the required evidence. Do not infer reasoning the student did not write. Quote the student only when the words appear in the answer. Mark uncertainty when the available evidence does not support a reliable judgment.

**Assessing - Context-aware**

> Assess the submitted answer against the supplied answer key and rubric. Consider supplied hint history, earlier attempts, and contradictions when explaining your feedback. Do not let a hint or earlier attempt change whether the current answer matches the key or justify unsupported rubric credit. Treat response time as context, not proof of understanding. Quote only words present in the student's answer and mark uncertainty when evidence is insufficient.

**Assessing - Conservative**

> Assess the submitted answer against the supplied answer key and rubric. Award a rubric point only when the answer clearly supports it. When the answer is ambiguous, incomplete, or inconsistent with earlier evidence, state the uncertainty rather than inferring the student's reasoning or asserting an unsupported misconception. Explain what evidence is missing and quote only words present in the student's answer.

For these six templates, the omitted common suffix instructs the model to use only supplied context, treat learner and course content as data, and return the requested structured output. The added instructions do not replace the built-in prompt or change the application rules.

**First-stage Expert evaluation (`COMP7608B_Lec08.pdf`).** All four Expert settings (**Baseline**, **Expert · Rules**, **Expert · Procedural**, and **Expert · Exemplar**) were executed live on the same frozen full lecture deck, `COMP7608B_Lec08.pdf` (73 pages, 73 extracted passages, SHA-256 prefix `d16b66702316`), using `openai/gpt-6-luna` via OpenRouter at the provider default temperature, local `bge-m3` embeddings, Poppler slide-image recovery (`pdftoppm`), and identical output schemas and validators.

*Initial failures and iterative refinement.* Before redevelopment, only **Baseline** (`21568e68`) completed end-to-end; initial template runs stopped in `needs_review`:
- `Rules` (`8c497bae`: 110 s, US$0.0278) failed during section extraction on wrong-chunk attributions, and after a section-prompt patch (`834a3ebc`: 687 s, US$0.5176, 63/67 lessons) still flagged 4 lessons due to thin-bullet over-splitting (e.g. a 10-word bullet turned into `tool-argument-filling`) and curriculum `teaches` over-claims that created a deadlock between scope review and grounding review (e.g. `read-model-card-scores`).
- `Procedural` initially collapsed prerequisites to 1–2 edges (`e0590042`: 1 prereq, 60/61 lessons, US$0.4287; `1b06c246`: 2 prereqs, 56/57 lessons, US$0.3873) because its earlier counterfactual test ("answer a basic question about B without understanding A") rejected nearly every dependency, while thin splits (e.g. a 9-word sentence turned into `known-solution-validation`) failed grounding. Subsequent tests surfaced an off-by-one alias error (`d94a1774`: emitted `s48` for page 48 against global aliases `s40..s47`, US$0.0297) and multi-sentence `teaches` scopes plus exhausted quiz-only/schema retries (`218f6bfd`: 47/50 lessons, US$0.3288; `f1d52dcc`: 55/58 lessons, US$0.4665).
- `Exemplar` (`92972b4b`: 102 s, US$0.0235) halted on an unretried section-level `cyclic_graph` after completing 9 of 10 sections.

Five shared fixes resolved these issues without weakening grounding gates: (1) adding a teachability floor, direct-use prerequisite criterion, acyclic edge rules, and concise summary-faithful `teaches` scopes across all three variants in `prompts_variants.py`; (2) switching section extraction in `analysis.py` to section-local aliases (`s0..sN`) and moving `validate_graph` into `generate_grounded`'s bounded retry loop in `grounding.py`; (3) adding fallback PDF slide-image recovery on `attempt >= 1` for non-quiz grounding/scope failures and reloading saved `reviewDrafts` slide transcriptions on retries in `materials.py`; (4) allowing one bounded quiz-only or schema-error polish pass without loosening full-lesson grounding limits; and (5) excluding `SlideTranscription` and independent reviewer calls from `previousRunFailure` prompt injection on retries in `workflows.py`.

*Completed first-stage runs.* After these fixes, all four styles completed and published 100% of their generated lessons and starter questions with zero flagged items:

| Expert template (run ID) | Automated pass (lessons) | Concepts / topics | Prerequisites / related | Layers (B / I / A) | Slide recoveries / repairs | API calls & tokens (in / out) | Time & cost | Human review: supported concepts | Human review: justified prereqs | Example observation |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- | :--- | :---: | :---: | :--- |
| Baseline (`21568e68`) | 77 / 77 (0 flagged) | 77 / 15 | 8 / 36 | 70 / 6 / 1 | 5 / 39 | 527 calls (3.70M / 395k) | 875 s, US$0.6108 | `[TODO]` | `[TODO]` | Finer-grained catalog (77 concepts, highest call count and cost); keeps sparse links (e.g. `Token precision` → `Token F1`) and 1 advanced synthesis goal (`Version and reuse accepted proposers`). |
| Expert · Rules (`33aaf382`) | 52 / 52 (0 flagged) | 52 / 10 | 16 / 23 | 36 / 14 / 2 | 1 / 16 | 304 calls (2.02M / 229k) | 530 s, US$0.3409 | `[TODO]` | `[TODO]` | Most compact catalog and lowest cost/latency (44% cheaper than Baseline); produced the deepest pyramid (16 prereqs, 14 intermediate, 2 advanced, e.g. `Accuracy/exact match` → `MMLU`, `GSM8K`, short-answer). |
| Expert · Procedural (`5905514c`) | 58 / 58 (0 flagged) | 58 / 10 | 14 / 30 | 46 / 12 / 0 | 2 / 21 | 357 calls (2.15M / 265k) | 619 s, US$0.3664 | `[TODO]` | `[TODO]` | Balanced 10-topic grouping with 14 direct-use prerequisites (e.g. `Token Precision, Recall, and F1` → `skill-router precision and recall`), but assigned 0 advanced concepts on this run. |
| Expert · Exemplar (`96e02e2c`) | 57 / 57 (0 flagged) | 57 / 12 | 11 / 22 | 46 / 10 / 1 | 7 / 23 | 366 calls (2.21M / 276k) | 691 s, US$0.3840 | `[TODO]` | `[TODO]` | Clean three-layer pyramid (`46/10/1`, advanced goal `Using held-out proposals for a model-side screen`) and strongest use of slide-image recovery (7 lessons enriched from rendered PDF slides). |

*Interpretation limits.* One completed run per style is a preliminary behavioural comparison and cannot show run-to-run consistency. Automated grounding, scope, and key-verification pass rates (100% across all four completed runs) confirm pipeline reliability under shared validators, not complete pedagogical coverage or human-verified accuracy. A team member still needs to audit the generated concepts and prerequisite links against `COMP7608B_Lec08.pdf` to fill the two human-review columns and check for missing or merged topics.

**Tutor and Assessing evaluation (27 cells, in progress).** Each cell is one published Expert generation crossed with one Tutor template and one Assessing template: 3 generations × 3 Tutor templates × 3 Assessing templates = 27 cells. The generations are **Expert · Rules** (`33aaf382`), **Expert · Procedural** (`5905514c`), and **Expert · Exemplar** (`96e02e2c`). Baseline (`21568e68`) stays in the first-stage table above and is not part of this grid. Every cell uses the same settings:

| Setting | Value |
| :--- | :--- |
| Material | `COMP7608B_Lec08.pdf`, the published Workbench generation for that Expert style |
| Concepts | 6, the first 6 concepts in published order. The same sampler is used for every cell. |
| Activities per learner | 12 |
| Learners | All 4 built-in profiles: Novice, Intermediate, Misconception-prone, Hint-dependent (108 episodes) |
| Student simulator | Belief-based pilot |
| Agent model | `openai/gpt-6-luna` (backend default) for Expert, Tutor, and Assessing |
| Student model | `openai/gpt-oss-120b`, a different model from the agents |
| Held-out exams | None. These runs do not author or sit a pre-test or a final test. |
| Temperature | Provider default |
| Execution | 4 cells at a time. A failed learner is retried once. |

The student model is separate so the Assessing agent is not grading answers written by the same model. Belief-based replies can be multiple-answer, fill-in, or open. A practice item counts as correct only when the whole answer matches: every required option, every blank, or a full rubric score. A partial match stays incorrect in the correct-answer count and is still stored as a partial rubric score.

The 6-concept sample is a limit of this comparison. Published order lists basic concepts before intermediate and advanced ones, and the prerequisite links in these three generations point from an early concept to a much later one. The first 6 concepts therefore contain no prerequisite edge. Eligibility rules still apply, but **Tutor - Prerequisite-focused** has no in-sample link to follow. The comparison can show differences in activity choice, remediation, hints, and marking. It cannot show a difference in prerequisite sequencing.

A one-learner pilot on the same settings, **Expert · Procedural** × **Tutor - Learner-focused** × **Assessing - Correctness-focused**, finished before the grid. Run `34dd1895` used Novice only: 12/12 activities, 8 correct, 0 hints, 2 demonstrated levels, 0 prerequisite, update, and repeat violations, 104 calls, 398 s, US$0.0257. That cell is being run again inside the grid with all 4 learners, so `34dd1895` is a pilot and not one of the 27 cells.

Recorded measures for each episode are activities completed, correct answers, hinted activities, demonstrated levels, prerequisite violations, invalid updates, repeated questions, calls, latency, and cost. There is no pre-test or post-test score. The grid was still running when this section was written, so the outcome table is not filled.

| Cell | Activities completed | Correct answers | Demonstrated levels | Violations | Cost (US$) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 27 cells × 4 learners | `[TODO]` | `[TODO]` | `[TODO]` | `[TODO]` | `[TODO]` |

`[TEAM TODO: complete the human review counts for the four Expert runs above on COMP7608B_Lec08.pdf, and fill the 27-cell outcome table from the finished grid, including any retried learners and failed episodes.]`

### 5.4 Results

The live runs in Table 2 used `openai/gpt-6-luna` at temperature 0.2, Lecture 2 material, the adaptive Tutor, and the grounded, utility, and weighted setup from Section 2. The episodes are short, so the score change is a check on behaviour. It is not a learning result, and it does not rank the other 26 prompt cells.

| Run | Setup | Profile | Pre → post | Change | State match | False demonstration | Violations | Cost (US$) |
| :--- | :--- | :--- | :--- | :---: | :--- | :--- | :--- | :---: |
| `722a04b0` | 5 concepts, 3 questions | Intermediate | 0.67 → 0.33 | −0.33 | F1 0.14 | — | 0 / 0 / 0 | 0.0066 |
| `722a04b0` | same | Misconception-prone | 0.27 → 0.20 | −0.07 | F1 0.20 | — | 0 / 0 / 0 | 0.0072 |
| `722a04b0` | same | Hint-dependent | 0.27 → 0.47 | +0.20 | F1 0.13 | — | 0 / 0 / 0 | 0.0074 |
| `64f8c6f7` | 5 concepts, 2 questions | Novice | 0.13 → 0.20 | +0.07 | difficulty accuracy 0.93, F1 0.24 | none estimated | 0 / 0 / 0 | 0.0065 |
| `23f5acb8` | 7 concepts, 4 questions | Novice | 0.33 → 0.48 | +0.14 | — | — | 0 / 0 / 0 | 0.0052 |
| `23f5acb8` | same | Intermediate | 0.86 → 0.95 | +0.10 | — | 0.00 | 0 / 0 / 0 | — |
| `23f5acb8` | same | Misconception-prone | 0.86 → 0.76 | −0.10 | — | 0.00 | 0 / 0 / 0 | 0.0071 |
| `5935f369` | 7 concepts, 2 questions, Workbench | Novice | 0.33 → 0.62 | +0.29 | — | 0.00 | 0 / 0 / 0 | 0.0047 |

*Table 2. Selected live episodes. Violations are prerequisite violations, invalid updates, and repeated questions, in that order.*

The same violation counts hold for the episodes omitted from the table. In all 36 completed live episodes, prerequisite violations, invalid updates, and repeated questions were 0. The novice episode in `722a04b0` failed and was retried separately. One hint-dependent episode in `2c9c90e9` stopped at the budget.

Offline, with scripted answers, the full grid completed: 3 Expert styles × 3 Tutor styles × 3 Reviewer styles × 4 profiles × 2 repeats = 216 episodes, plus 24 baseline episodes. No workflow failed. These runs show that the harness can apply the conditions. They provide no evidence about learning.

A live baseline comparison remains to be run. The code can compare, on the same materials and the same number of questions, a fixed order along the prerequisite chain and a Tutor with no memory of earlier sessions. Every live batch so far uses the adaptive Tutor only. `[TEAM TODO: run adaptive, fixed-order, and memory-free conditions on one frozen release of 5 or 7 concepts, with 4 profiles, at least 3 repeats, and 8–12 questions. The expected cost is under US$0.50. Fill the table below. If the run is not completed, state that the baseline was checked offline only.]`

| Condition | Mean gain (with spread) | Topics demonstrated at the target | Ineligible or repeated actions | False demonstration | Mean cost (US$) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| LearnLoop, adaptive | `[TODO]` | `[TODO]` | 0 in the runs above | `[TODO]` | `[TODO]` |
| No memory of earlier sessions | `[TODO]` | `[TODO]` | `[TODO]` | `[TODO]` | `[TODO]` |
| Fixed order along the prerequisite chain | `[TODO]` | `[TODO]` | `[TODO]` | `[TODO]` | `[TODO]` |

### 5.5 Human check of model judgments

Two steps in the system are themselves judgments: whether a lesson is supported by the cited pages, and whether a rubric score matches the student’s writing. The criteria are as follows.

1. A lesson or explanation may state only what the cited pages support. Any other claim is unsupported.
2. A reader who has only those pages should reach the stored key, and no other option should also be fully correct.
3. A rubric score must match the student’s text. A misconception quote must be copied from that text.

Automatic screening of 36 packs from a 12-concept unit, using `gpt-6-luna`, `gemini-2.5-flash`, and `bge-m3` similarity, flagged 10 packs (`review-packet-002.md`). `[TEAM TODO: two members should score 20–30 source reviews and 20–30 marked answers from the saved call files, report the rate of agreement with the model, and give one or two disagreements.]`

### 5.6 Interpretation and limitations

Two to five questions leave most items on a 5–7 concept quiz unpractised. A guess on a four-option item also moves the score. A change of about 0.1 is about one item on a 15-item quiz. These runs therefore test behaviour: the Tutor returned to the missed topic, locked topics stayed locked, and one sound answer was not recorded as mastery.

The low state-match scores have the same cause. After a few questions, most topics are still untouched, so a score over the whole map stays around 0.11–0.24. On the items that were attempted, difficulty accuracy reached 0.93 in `64f8c6f7`. Misconception precision was 0 where it could be measured. The Reviewer often named a plausible confusion from the wrong option, and that text did not match the simulator’s hidden label. Short multiple-choice answers give little evidence for a specific misconception.

An early one-concept trial marked a topic as demonstrated while the post-test fell. In the later runs where this rate was recorded (`23f5acb8`, `5935f369`), the rate was 0.00. This result agrees with the two-answer rule on a very small sample.

The simulated students use assumed learning and hint rates. The material is one lecture, and the generator is one provider model. The evidence does not support a claim of learning gain for real students.

---

## 6. Contributions and Attribution

| Member | Contribution |
| :--- | :--- |
| Member 1 | `[TEAM TODO]` |
| Member 2 | `[TEAM TODO]` |
| Member 3 | `[TEAM TODO]` |
| Member 4 | `[TEAM TODO]` |

The implementation uses FastAPI 0.128.4, Uvicorn 0.40.0, SQLAlchemy 2.0.46, Alembic 1.20.0, Pydantic 2.12.5, pydantic-settings 2.12.0, sqlite-vec 0.1.9, httpx 0.28.1, pypdf 6.11.0, filelock 4.2.8, and jsonschema 4.26.0. The frontend uses Next.js 16.4.2, React 19.3.0, Zod, react-markdown, and KaTeX. Slide images use Poppler’s `pdftoppm` when it is installed. Model access is through OpenRouter and Ollama, with BAAI `bge-m3` [7]. The evaluation unit is COMP7608B Lecture 2. `[TEAM TODO: name any other sample file included in the ZIP.]`

Tests and the offline harness use stand-in model and embedding clients. Offline mode is labelled `workflow_only`. Those results describe the software path. They are not results about model quality.

Relative to the proposal, the following items remain unfinished: LangGraph, Docker, multi-user accounts, missions and rewards, optical character recognition, a path in which the Reviewer orders a follow-up question, and a dollar cap on ordinary study sessions. The Tutor can request a question. The Reviewer cannot.

---

## AI-Use Declaration

`[TEAM TODO: name each tool and model, for example Cursor and ChatGPT, and state what each one helped with.]`

AI assistance was used for implementation, including API and page scaffolding, tests, worker locking, and evaluation logs, and for this report, including structure against the course guideline, reading the run logs, and editing. Group members checked the progress rules, prompts, tests, and the figures above by running them. Project prompts, with keys and personal details removed, are included in the submission ZIP under `ai_use/`. `[TEAM TODO: state here if any early chats were not saved.]`

---

## References

1. Yao, S., Zhao, J., Yu, D., Du, N., Shafran, I., Narasimhan, K., & Cao, Y. (2023). *ReAct: Synergizing Reasoning and Acting in Language Models.* ICLR.
2. Shinn, N., Cassano, F., Gopinath, A., Narasimhan, K., & Yao, S. (2023). *Reflexion: Language Agents with Verbal Reinforcement Learning.* NeurIPS.
3. Lewis, P., et al. (2020). *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks.* NeurIPS, 33, 9459–9474.
4. Corbett, A. T., & Anderson, J. R. (1994). *Knowledge Tracing: Modeling the Acquisition of Procedural Knowledge.* User Modeling and User-Adapted Interaction, 4(4), 253–278.
5. Ma, W., Adesope, O. O., Nesbit, J. C., & Liu, Q. (2014). *Intelligent Tutoring Systems and Learning Outcomes: A Meta-Analysis.* Journal of Educational Psychology, 106(4), 901–918.
6. Kwon, W., et al. (2023). *Efficient Memory Management for Large Language Model Serving with PagedAttention.* ACM SOSP. Cited because Lecture 2, the evaluation unit, discusses this result.
7. Chen, J., et al. (2024). *BGE M3-Embedding.* arXiv:2402.03216.

---

## Appendix: items to complete before PDF export

Remove this appendix from the submitted file.

- [ ] Fix the 9 failing tests (`test_organization.py`, `test_slide_evidence.py`, `test_tutor_chat.py`) so the tagged tree passes. Current count: 302 passed, 9 failed, 311 collected.
- [ ] Fill the 27-cell Tutor and Assessing outcome table in Section 5.3 from the finished grid.
- [ ] Run the live baseline in Section 5, or state that it was checked offline only.
- [ ] Complete the human check of source reviews and marking.
- [ ] Fill in the git version, each member’s contribution, and the AI-use notes.
- [ ] Export the PDF and follow the README on a clean machine.
