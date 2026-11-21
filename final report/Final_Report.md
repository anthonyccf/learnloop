# [Group 72] LearnLoop: A Stateful Agentic Platform for Adaptive Learning

**Course:** COMP7608B Large Language Models — Final Project Report  
**Deadline:** 25 November 2026

**Submitted version:** `[TEAM TODO: git tag or commit, for example v1.0-final]`  
**Repository:** `[TEAM TODO: link, if the repository is shared. The submission ZIP includes the source snapshot.]`

---

## Summary

LearnLoop was developed for university students revising from their own lecture notes. Concepts and prerequisite links were extracted from an uploaded PDF or text file. One checked question was assigned at a time, and each answer was saved so that practice could be resumed in a later session.

Teaching responsibilities were divided among three agents. Concept maps, lessons, and starter questions were prepared by the Expert. Activities were selected by the Tutor from topics whose prerequisites had been met. Each submission was marked by the Reviewer (called the Assessing agent in the Workbench), and feedback was based on a private key and marking criteria. Publication and progress were governed by program rules. For example, a correct answer given after a hint was recorded as assisted practice.

The application was run locally, and course records were saved in SQLite. Relevant course passages and submitted answers were sent to an external model provider when a model judgment was required. A separate evaluation tool was used to generate student responses. Throughout this report, a *live simulation* means that actual model calls were made for a simulated learner. No human learner took part in those sessions.

Across the 36 completed Lecture 2 simulations, no topic with an unmet prerequisite was assigned, no practice question was repeated within an episode, and no invalid progress update was recorded. For a turn in which a prepared question was assigned and the response marked, the two agent calls together were estimated to cost US$0.0006. The simulated student’s own model calls were accounted for separately.

---

## 1. Users and Proposal Continuity

### 1.1 Users and needs

The design was guided by four needs identified for a university student revising a technical course in which later topics depended on earlier ones.

1. Prerequisites had to be made explicit when the order of lecture slides left the connection unclear.
2. Explanations had to be supported by the slides, and a proposed answer key had to be checked before it was used for marking.
3. Independent answers had to be distinguished from assisted answers, and a single correct choice had to be treated as limited evidence of understanding.
4. Evidence of earlier practice had to be retained so that topics still requiring attention could be identified when the student returned.

These needs were used to define how a course was prepared, how activities were chosen, and how progress was recorded.

### 1.2 Requirements and scope

Five requirements were specified for a course unit of approximately 5–20 concepts.

1. Support was required for readable PDF or text files of up to 20 MB and 200 pages. Each concept, link, lesson, and question had to be traced to a source page.
2. A quiz had to be withheld until every direct prerequisite had been demonstrated at the required level.
3. A topic could be marked as demonstrated only after two different questions had been answered without hints and the marking criteria had been met at the target difficulty. Review was to be scheduled after 7 days. Two consecutive clear failures after demonstration were to be recorded as a confirmed weakness.
4. Answer keys and marking criteria had to be kept on the server until an answer was submitted.
5. Interrupted work had to be recoverable, and a repeated submission had to be counted only once.

The prototype was designed for one person using one machine. Shared class accounts, missions and rewards, web search, and optical character recognition for scanned handwriting were excluded from scope. An optional vision model could be used to read slide figures when Poppler was available.

### 1.3 Planned work and delivered work

The proposed and delivered features were compared in Table 1.

| Proposal item | Status | Delivered form |
| :--- | :--- | :--- |
| Three agents in one prepare–practise–assess loop | Delivered | A separate package and job type were assigned to each of the three agents. |
| A source-checked concept map with three difficulty levels | Delivered, with a smaller starter set | One lesson and two checked basic questions were prepared for each concept at setup. Harder questions were written when requested by the Tutor. |
| Ranked Tutor actions and saved plan versions | Delivered | Eligible options were scored, one of the top 12 was selected by the Tutor, and a reason was given. Each plan revision was saved. |
| Rubric feedback, misconceptions, timing, and contradictions | Delivered, and extended | Single-choice, multiple-answer, fill-in, and short written responses were supported. |
| A learner record with an explicit weakness rule | Delivered | A two-failure rule was implemented in `core/domain.py` for confirming a weakness after demonstration. |
| A published, versioned course | Delivered | Each session was tied to its starting release so that work already in progress was preserved during a later rebuild. |
| A prompt workbench | Added after the proposal | Prompt versions could be saved, Expert styles selected, and material held after an automatic check approved by a human reviewer. |
| LangGraph | Changed | A Python dispatcher with SQL job leases and checkpoints was used (`runtime/workflows.py`). Job state was kept in the same database as learner updates so that related changes could be saved together. |
| PostgreSQL, Qdrant, and Docker | Changed | SQLite with `sqlite-vec` was selected as the default for a setup requiring Python and npm. The earlier database adapters were retained. |
| Token, cost, and latency records | Delivered for preparation, the Workbench, and evaluation | Each call was recorded in these runs. Individual practice requests were limited by time and token count. A session-wide dollar cap was not implemented. |
| 27 prompt combinations, four simulated students, and two baselines | Offline comparison completed; proposed live comparison with both Tutor baselines outstanding | Nine prompt options were defined in Section 2. One combination was used in the live Lecture 2 study. Offline, 216 study episodes and 24 baseline episodes were completed (Section 5). |
| Many learners on one shared course, plus missions and rewards | Not delivered | Development was focused on source checks, grading, and saved progress. |

The original aim of a learning agent that retained progress across sessions was maintained. Changes were made to the application infrastructure and to the extent of the evaluation completed. `[TEAM TODO: state whether the teaching team was notified of any change. If no notice was required, retain this paragraph.]`

---

## 2. Design and Implementation

### 2.1 Workflow

Requests from the student page were received by FastAPI. For course preparation, activity selection, and assessment, a job was saved in SQLite and the relevant agent was called by a background worker. The answer key was kept on the server while a question was open.

```
Student page  ->  API checks  ->  job in SQLite  ->  worker
                                      ^              |
                                      |              +-> Expert, Tutor, or Reviewer
                                      |                     |
                                      +---- saved result ---+
                                                    |
                              OpenRouter (gpt-6-luna) and local Ollama (bge-m3)
```

*Figure 1. Request handling and storage of agent results. Answer keys were withheld until assessment.*

**Preparation.** The uploaded file was divided into overlapping passages of about 1,600 characters, and the page number was retained for each passage (`core/domain.py`). Local `bge-m3` embeddings were stored in `sqlite-vec` for search. Each section was read by the Expert, concepts were proposed with citations, and repeated concepts were merged across files. Two model calls within the Expert workflow were used to construct the map. Candidate links between concepts were proposed in the first call. In the second, each proposed link was reviewed against the lecture evidence. This review concerned the course map. The Reviewer who later marked student answers was called only after a submission. A prerequisite could be retained, marked as a related link, or removed. Cycles and unknown identifiers were rejected.

Each concept was assigned a basic, intermediate, or advanced layer. The content to be taught and the knowledge assumed were specified before the lesson and two basic questions were drafted. A fresh model call was given each question and its cited pages, with the proposed key withheld. After a failed check, up to two revisions were allowed, with a wider set of pages supplied on each attempt. Material that still failed was held for human review (`manual_review.py`). A fixed course release was published once the required material had passed.

**Planning.** Each session was tied to a fixed course release. Topics with unmet prerequisites were filtered out by `core/planning.py`. The remaining activities were ranked by need, uncertainty, review urgency, recent performance, and fit with the learner’s goal. Up to 12 options were presented to the Tutor, and one was selected with a short reason for the learner. An unused, checked question was assigned when one was available at the required level. Otherwise, a new question was requested from the Expert and checked before assignment.

**Assessment.** Selected options and filled blanks were checked against the private key. Written reasoning was assessed by the Reviewer against the marking criteria. Uncertainty or a conflict with an earlier answer could be flagged, and any quotation was checked against the student’s words. Credit could be reduced for weak reasoning. Full marks could not be awarded for a wrong choice. The mark, updated learner record, and activity were saved together after `assess_evidence()` was applied. Feedback was displayed before the next question was requested.

**Continuation.** Tutor chat used while a question was open was recorded as a hint. After submission, the evidence for that answer was kept unchanged. The next plan was built from the saved record.

### 2.2 Architecture options and rationale

Four aspects of the architecture were considered: how teaching tasks should be divided, how each agent should be called, which decisions should be governed by fixed rules, and what should be remembered between sessions.

**One agent or several specialists.** A single agent was considered for reading lectures, selecting activities, and marking answers. Coordination would have been simpler, but course material, learner history, and private keys would have been brought into the same conversation. Whether an answer was disclosed in a hint would then have depended heavily on the model following its instructions.

The three agents were implemented as separate roles with different prompts and inputs. A different underlying language model was not required for each role. Access to information could therefore be limited according to the task being performed. The Expert was given the lecture material, the Tutor was given eligible activities and the learner record, and the Reviewer was given the submission, private key, and marking criteria. A poor result could therefore be traced to a particular step, although extra coordination and model calls were required. Because errors could be shared across calls to the same model, each drafted question was also given to a fresh call to be solved from its cited passages with the proposed key hidden.

**Agent control or a fixed workflow.** An agent allowed to choose its own tools could have adapted its sequence of actions to an unexpected request. However, source checks were required before assignment and prerequisite checks before practice. A Python worker was therefore used to run the required steps in order. Outputs were checked and completed work was saved so that an interrupted session could be resumed. New routes had to be implemented explicitly.

**Coordination between agents.** Direct delegation, a separate supervisor model, and Tutor-led planning were considered. Direct delegation would have allowed more paths through a session, making the decisions harder to trace. With a supervisor, an extra model call would have been required for routing, and the task could have been assigned to the wrong agent. A fixed teaching sequence would have been easier to trace, but could not readily have been adjusted after a student’s last answer.

Responsibility for choosing the next activity was assigned to the Tutor. When a suitable checked question was unavailable, one was requested from the Expert. A separate Reviewer task was started when the learner submitted an answer. Its findings were saved for the next planning step, which was started when the learner requested another activity.

Teaching decisions were thus divided from control of the workflow. The next activity was chosen by the Tutor. Routing, prerequisite checks, and storage were handled by the worker. The Tutor’s choice was limited by the quality of the course map and by the activities offered.

**Model judgment and program rules.** Language models were used to extract concepts, explain questions, and assess written reasoning against a rubric. Eligibility and changes to the learner record were determined by program rules because model judgments could vary across calls. Even a persuasive explanation was recorded as assisted when a hint had been used. This rule could be tested directly, although its threshold had been set by the team and had yet to be validated with students.

**Conversation history or a structured record.** A transcript could have preserved the learner’s wording, but earlier progress would have had to be inferred again in each session. Instead, the answer, plan, and evidence were saved for each topic and difficulty. Hint use and reviews due could then be retrieved directly. Explicit update rules were required, and aspects of understanding outside the recorded fields could have been missed.

The architecture was selected to allow decisions to be inspected, prerequisites to be enforced, and interrupted work to be resumed. Behaviour within this architecture was evaluated in Section 5. A comparison with single-agent and supervisor-led designs would require common course materials and tasks, with source accuracy, grading, learning outcomes, response time, and cost measured under each design.

### 2.3 Prompt options and the selected setup

Three prompt options were defined for each agent. Only the added instruction was varied. The required output, source checks, and progress rules were held fixed. The resulting 27 combinations (3 × 3 × 3) were defined in `learnloop/evaluation/variants.py`.

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

The *grounded*, *utility*, and *weighted* prompts were selected for the Expert, Tutor, and Reviewer respectively.

With the grounded prompt, supporting pages were required for each lesson or question. Map organization was emphasized by the structural prompt, and a check of the writer’s own draft was requested by the verified prompt. Grounded was selected because a separate call had already been included to solve each question with the key hidden.

Utility was selected because a score reflecting several learning needs was already supplied for each eligible activity. More weight was given to the recent learner record by the state prompt and to prerequisite order by the graph prompt.

With the weighted prompt, hints, response time, and earlier attempts could be considered when a mark was explained. Credit was still determined by the key and marking criteria. Less emphasis was placed on learner history in the correctness prompt. In the conservative prompt, uncertainty was to be stated when the evidence was weak. Differences in feedback quality required separate evaluation.

The grounded, utility, and weighted prompts were selected on design grounds for the live Lecture 2 study. Their relative quality was not established by the offline study. In that study, three instructions for each of the three agent roles were combined, giving 27 combinations, and scripted answers were used to check that every combination could be run. A different set of 27 conditions was used for Lecture 8. There, the three Expert inputs were already-published course maps, and the Tutor and Assessing templates were varied during simulated practice (Section 5.3).

A second setting, `ORGANIZATION_PROMPT_VARIANT`, was provided for the Expert’s course-building prompts in `agents/expert/prompts_variants.py`. The form of instruction was varied across four styles. The same JSON output was required in each case.

| Style | Form of the instructions | Use |
| :--- | :--- | :--- |
| baseline | The production prompt in `agents/expert/prompts.py`. | Default for uploads and the reference prompt in the four-style Lecture 8 comparison. |
| rules | Labelled constraints, followed by a short self-check. | Workbench and evaluation. |
| procedural | Numbered steps, with a test at each step. | Workbench and evaluation. |
| exemplar | The same rules, taught with examples from introductory statistics, so the examples do not copy the lecture under test. | Workbench and evaluation. |

In the Lecture 8 comparison, *Baseline* was the name given to the standard Expert prompt used to build a course map. The other three styles were applied to the same lecture file (`COMP7608B_Lec08.pdf`), as reported in Section 5.3. The fixed-order and memory-free *baselines* in Section 5.4 served a different purpose: they were alternative ways of choosing practice activities once a map had been prepared. Human review of the Lecture 8 concepts and prerequisite links was still pending.

During practice, the allowed activities were calculated independently of the prompt setup. The Tutor was required to return one of the offered identifiers. If another identifier was returned, the run was stopped with `invalid_plan`.

### 2.4 Decisions and limits

| Decision | Responsible component | Check or stopping rule |
| :--- | :--- | :--- |
| Which ideas a section teaches | Expert | A citation could not be resolved, or a draft was still unsupported after two revisions. |
| Which links are prerequisites | Expert (link proposal and review) | A proposed map was rejected if a new link was introduced during review or if a cycle was detected. |
| Whether a drafted question is sound | A second Expert call | The proposed key was rejected by the solver and disagreement persisted after repair. The question was withheld. |
| The next topic, action, and level | Tutor | An unlisted activity was selected or a prerequisite changed before the plan could be saved. |
| A new question when the bank is empty | Tutor, then Expert | Generation failed. A checked question could be reused if one was available. |
| Feedback, a misconception quote, and uncertainty | Reviewer and learner-record rules | A quotation had to be found in the submitted response before it could be used as evidence. A hinted, partial, or uncertain response could be marked and saved, but it could not count toward demonstration. |
| Whether work continues | Worker | The run was paused before any model call if the API key was missing. It could also be stopped by the learner. Completed sections were retained. |

### 2.5 Learner record

Each concept was assessed separately at basic, intermediate, and advanced difficulty. Its target was the level at which understanding had to be demonstrated before a dependent topic could be unlocked. The curriculum layer was used when one had been assigned. Otherwise, the specified target difficulty was used, with intermediate as the default. A learner could therefore complete a basic practice activity while still working toward an intermediate target.

A new topic was recorded as *unassessed* and could be marked as *developing* after an initial attempt. During ordinary practice, the topic was marked as *demonstrated* only after two different questions had been answered without hints and the marking criteria had been met at the target level. A review was then scheduled for seven days later. After demonstration, another review was triggered by one clear miss. A weakness was confirmed after two consecutive unhinted misses on different questions, and the level was returned to *developing*. Two new qualifying answers were required for recovery. A topic requiring intermediate understanding could not be unlocked by success at the basic level.

After a miss, a hint, or an uncertain answer, the difficulty of the next question was reduced by one level where possible. It was raised again only after the lower level had been demonstrated.

### 2.6 Models, prompts, tools, and state

Content was generated with `openai/gpt-6-luna` through OpenRouter. Separate models could be configured for verification and slide images. For search, each passage was represented by 1,024 values generated locally with BAAI `bge-m3` through Ollama. A temperature of 0.2 was used and a seed was recorded for the earlier evaluation runs. The separate Workbench settings are listed in Section 5.3. Requests were limited to 90 seconds and up to eight model calls could be run at once.

A separate prompt file was maintained for each agent. Prompts based on the built-in `v2` set could be saved in the Workbench. Each reply was checked for the fields required by its task.

Tool use was controlled by the worker, and direct database writes were not permitted from the model. Passage retrieval, source review, publication, activity selection, Expert question requests, marking, evidence updates, and plan revisions were recorded in the activity trace.

SQLite was used as the sole store in the default configuration. Course releases were fixed and hashed. Sessions, answers, plans, jobs, and learner records were stored separately. Each question was divided into a public part containing the stem, choices, and source page, and a private part containing the key, marking criteria, and explanation.

### 2.7 Design choices

Five design choices were made in response to the teaching and operating requirements.

1. Progress rules were implemented in code so that they could be tested directly. The thresholds of two successes, two failures, and seven days were chosen by the team. They were not estimated from student data.
2. Every section was read during preparation so that definitions could be retained even if they were missed by a short search. About 3–11 minutes were required to prepare a unit of 5–7 concepts.
3. Only basic questions were written during setup to limit initial cost. When a harder question was first needed, additional model time was required for preparation and checking. The 21 Expert question calls reported in Section 4 had a median duration of 3.58 seconds and a 95th percentile of 13.85 seconds. These were call durations. The total time from the learner’s request to display of the question was not established by this measure.
4. The Tutor was offered at most 12 eligible actions. No invented topics or prerequisite violations were recorded in the observed runs.
5. SQLite with a file lock was selected for a simple local setup. This choice was suited to one learner, with limited support for simultaneous writes by many students.

### 2.8 Task traces

Three cases were examined. Ordinary practice was traced through a saved session. A change of request and a failure of source support were examined through the corresponding program paths.

**Ordinary task.** In live episode `2eaf22b3eaac07c3` (run `0a0e83f0`), two topics were available for practice: paged key-value storage (`c01`) and mixture-of-experts parameters (`c02`). Both topics were initially listed as *developing* under the pre-test initialization rule. An incorrect answer had been recorded for `c01`, but the initial label did not mean that the learner had failed both topics.

1. The two basic activities, one for `c01` and one for `c02`, were each assigned a score of 4.0 by `core/planning.py`.
2. Topic `c01` was selected by the Tutor (`choose_candidate`, about 3.2 s), and saved question `c01|0` was assigned. The key was retained on the server.
3. The incorrect answer was recorded by `assess_evidence()`, and `c01` was retained at *developing*. A weakness was not confirmed because the topic had never been demonstrated.
4. After the miss, the priority of `c01` was raised to 5.0 for further practice (“remediate”), while `c02` remained at 4.0. A different checked question, `c01|1`, was assigned by the Tutor (about 2.2 s).
5. The correct option was selected and the following explanation was submitted: “It includes scheduling and kernels, so it does not isolate PagedAttention’s contribution.” Full credit was awarded for that marking point by the Reviewer (about 3.8 s), and the sentence was quoted as evidence. Only one qualifying answer had been recorded. Two were required for demonstration.

**Changed request.** In the test case, A had to be demonstrated before B could be practised, and B had to be demonstrated before C could be practised. A move to C was requested while a question on A was open. The request was declined because B, the direct prerequisite for C, was still unassessed. The prerequisite chain was then followed back to A, which was already being practised. The API returned HTTP 409 (`unmet_prerequisites`), identified B as the missing prerequisite, and offered continued practice on A. The open question and learner record were preserved (`prerequisite_block()` in `core/domain.py`).

**Failure.** In the failure case, a benchmark was named on a slide but was not explained. A proposed claim or key could therefore be rejected by the source check or independent solver (`agents/grounding.py`). Up to two revisions were allowed, with 6, 12, then 18 passages supplied across attempts. Material that still failed was stored privately. The problem was displayed for review with the key hidden (`manual_review.py`). Publication was withheld until the material was successfully regenerated or explicitly approved by a named reviewer. This behaviour was covered by `test_existing_failed_pack_is_repaired_or_remains_withheld`.

---

## 3. Reliability and Recovery

Recovery was tested with stand-in model clients and temporary databases. Failures were also observed during live sessions, where their effects on individual learners could be examined.

Two failures were of particular concern for learner progress. When a lesson was unsupported or a key was rejected by a second solver, two revisions were permitted. If neither revision passed, the item was kept private and the gap was displayed for review. When the same answer was submitted twice after a connection problem, the saved assessment was returned and the answer was counted once. The detection rules, retry limits, messages, and tests for all seven cases are listed in [Appendix A](#appendix-a-recovery-checks).

The effect of a failure on other learners in the same batch was examined in two recorded sessions.

In batch `722a04b0`, which covered 5 concepts, three simulated sessions were completed. The novice session was interrupted by a `ValueError` after 22 calls. Because a separate record had been kept for each learner, only the novice session was rerun (`c01c4eef`, `1fedf3cb`). The three completed sessions were retained, and course preparation, which had cost US$0.041, was reused.

In batch `2c9c90e9`, which covered 7 concepts and 5 activities, three sessions were completed at about US$0.011–0.012 each. Repeated hints were requested by the hint-dependent learner. Once the 64-call limit had been reached, the episode was stopped before another call was made, and the usage record was retained.

Repeated submissions were counted once, although a repeated model call could still incur a charge. If a connection was lost after a prompt had been processed by OpenRouter, a charge could be made for a reply that was never received. Such usage was marked `usageMayBeIncomplete`. Total calls and tokens were limited per evaluation episode. In ordinary practice, individual requests and retries were limited, but no session-wide dollar limit was imposed.

---

## 4. Non-Functional Requirements

Across 18 live batches, 1,541 completed model calls were measured. About 1,240 were used to generate simulated student responses. These calls were counted separately because the answers would have been supplied by students in ordinary use.

| Requirement | Target | Result |
| :--- | :--- | :--- |
| Practice-step latency | Median under 5 s per agent call, and 95th percentile under 10 s | Across 152 Tutor calls, the median was 3.34 s and the 95th percentile was 5.58 s. Across 128 Reviewer calls, the corresponding values were 4.17 s and 8.03 s. About 7.5 s of model time was estimated for a saved question by adding the two medians. |
| First harder question | A new checked question may be slower | Across 21 Expert question calls, a median of 3.58 s and a 95th percentile of 13.85 s were recorded. |
| Course preparation | Under 12 minutes for 5–7 concepts | For 5–7 concepts, 3.2–10.9 minutes (194–652 s) and 12–40 Expert calls were required. Seven concepts were prepared in 240 s for US$0.019 in `5935f369`, and five in 652 s for US$0.041 in `722a04b0`. |
| Cost | Under US$0.002 per student turn, and under US$0.08 per prepared unit | Mean costs of US$0.00029 and US$0.00032 were recorded for Tutor and Reviewer calls. A turn was estimated at US$0.00061 with a saved question and US$0.00090 with a new one. Preparation costs of US$0.016–0.059 were recorded for 5–7 concepts. US$0.0035–0.012 was recorded per simulated episode, including the cost of student responses. |
| Workload | Oversized files fail before a model call | Limits of 20 MB, 200 pages, and 1,000 passages were applied. Four worker attempts were allowed. Evaluation was capped at 80 calls or 400k tokens per concept and 64 calls or 250k tokens per episode. |
| Privacy | Keys and credentials remain off the page | A bearer token was required for every `/api` route. Secrets were stored in `.env`, and answer keys were withheld from the review screen. Course text and written answers were sent to OpenRouter. Embeddings were processed locally with Ollama. |
| Integrity | A crash or a repeated click leaves the record unchanged | Each mark was saved in one transaction with a version check, operation identifier, and course-release hash. No partial write or double-counted answer was observed in the automated tests or live episodes. |

The prototype was evaluated under the assumption of one local user, with `bge-m3` served by Ollama at `localhost:11434`, a funded OpenRouter key, and a readable text PDF or `.txt` file. Scanned pages without a text layer were rejected because optical character recognition had not been included.

---

## 5. Evaluation

### 5.1 Cases and judging rules

| Case | Input | Expected outcome | Observed outcome |
| :--- | :--- | :--- | :--- |
| Representative | Readable notes were uploaded, a course was published, questions were answered, and a new session was opened. Synthetic gradient-descent notes were used in the live journey and COMP7608B Lecture 2 in later runs. | Valid citations, hidden keys, developing status after the first qualifying answer, demonstration after the second, review in 7 days, and retention across sessions. | All 21 checks passed on 19 October. |
| Challenging: prerequisites | A topic was requested when its prerequisite was unassessed, developing, passed only with a hint, or passed below the target level. | HTTP 409, preservation of the open question, identification of the missing prerequisite, and an eligible alternative. | These outcomes were confirmed in API tests. No prerequisite violations were recorded in 36 completed live episodes. |
| Challenging: weak evidence | A correct answer after a hint, a correct choice with weak reasoning, and two misses after demonstration were examined. | Assisted or partial answers excluded from demonstration, review after a later miss, and a return to developing after the second miss. | These behaviours were observed in the weakness tests and live journey. |
| Failure | Unsupported material, duplicate submissions, worker interruption, and repeated hint requests were examined. | Material withheld after two unsuccessful repairs, one count per answer, recovery from a checkpoint, and stopping at the call cap. | Withholding was confirmed in the software test. Run `2c9c90e9` was stopped at the cap. |

### 5.2 Software tests and the live journey

Of 311 backend tests in the recorded run, 302 were passed and 9 failed. The earlier fault that allowed an item to be published after unsuccessful repairs was no longer observed in its regression test. The remaining failures were associated with course organization, slide-image reading, and Tutor chat. The frontend suite comprised 44 component tests, together with type and lint checks for the concept map, formulas, and practice state. These counts were taken from the recorded test run. They would need to be checked again against the code version submitted for marking.

On 19 October, a complete learning session was tested with the live API, generation model, embedding service, worker, and a temporary PostgreSQL schema with Qdrant for passage retrieval (`backend/docs/learning-journey-validation.md`). This check was conducted before SQLite was adopted as the default store. All 21 checks passed on the October setup. A map of three concepts and two links was built, six private questions were prepared, and the material was reused after a repeated upload. A blocked prerequisite was explained and a hinted answer was recorded as assisted. Demonstration was recorded only after two independent answers (learner version 4). A new question was supplied after the prepared pair had been used, and the learner’s history was retained in a later session. All three nodes and 39 formula lines were displayed. Operation of the learning loop was confirmed on this small unit. The factual accuracy of each lesson was outside the scope of that test.

### 5.3 Method

#### Pseudo-student setup

Pseudo-students were configured to test how LearnLoop responded to different starting levels, repeated mistakes, and requests for help. Two choices were made separately. A *profile* was used to set the learner’s starting characteristics. A *simulator* was used to determine how those characteristics were turned into an answer. The four built-in profiles are shown below. Their values were chosen as test conditions and were not estimated from student data.

| Profile | Starting ability (basic / intermediate / advanced) | Hint probability | Gain setting | Base response time | Initial misconceptions |
| --- | --- | ---: | ---: | ---: | --- |
| Novice | 25% / 12% / 5% | 20% | 0.10 | 45 s | None assigned |
| Intermediate | 80% / 55% / 30% | 10% | 0.07 | 20 s | None assigned |
| Misconception-prone | 65% / 40% / 20% | 20% | 0.07 | 35 s | Assigned to concepts 1, 4, 7, and so on in the selected order |
| Hint-dependent | 50% / 30% / 15% | 75% | 0.06 | 55 s | None assigned |

In the Workbench, profiles could be selected under **Pseudo-student tests → Simulated learners**. A custom profile could also be saved through **+ Create learner** by specifying a name, response model, and the settings shown in the table. For each test, the course material, agent templates, learner profiles, simulator, and number of activities were selected. A separate practice session was created for each selected learner. The profile settings and random seed were recorded with the run so that its conditions could be inspected later. The response time was simulated, with variation of up to 20% around the base value. It was separate from the measured time taken by a model call.

**Controlled answers (Lecture 2).** Each concept was initialized with the three ability values specified by the profile. Before an answer was generated, a seeded draw was used to set a target outcome. For example, a novice was initially assigned a 25% chance of being able to answer a basic question independently. The student model was given the public question and any teaching or hint provided. It was instructed to attempt a correct answer or make a plausible mistake according to the draw. The answer key was withheld. During practice, a hint request was sampled using the profile’s hint probability. After feedback, the increase in ability for the practised concept and level was capped by the gain setting. Thus, 0.10 allowed an increase of at most ten percentage points for the novice. The hidden values and target outcome were withheld from the Tutor and Reviewer. Whether the target was followed was checked against the submitted answer.

**Belief-based answers (Lecture 8).** The same four profiles were used, but a target of “correct” or “incorrect” was not assigned. Instead, each learner was given a private set of beliefs drawn from the lesson flashcards. For the misconception-prone profile, a mistaken belief was also drawn from the lesson’s description of a common mistake on designated concepts. Starting ability was used to set the initial chance of recalling an ordinary belief at the question’s difficulty. An answer was then generated from the recalled beliefs, the public question, and any teaching or hint supplied. The hint probability was applied only when the simulated learner was uncertain during practice and had not already been given a hint. For example, the 75% setting for the hint-dependent profile applied to those opportunities. It did not imply that hints would be requested on 75% of all questions. A belief revision was accepted only when it was supported by words from the teaching or feedback actually delivered. In this mode, the gain setting was used to strengthen recall of a supported revision. It was not treated as a measured increase in test score.

#### Lecture 2 assessment

At the start of each Lecture 2 episode, one multiple-choice pre-test item was administered for each concept at each difficulty level. The pre-test items were withheld from later practice. In the controlled evaluation runner, the pre-test score was saved for each tested concept and difficulty, and its starting state was recorded as *developing*. A pre-test response did not count as one of the two independent practice answers required for demonstration. After practice, separate post-test items were scored against the stored rubrics outside the Reviewer. For the controlled simulator, agreement was calculated as the proportion of graded replies whose correctness matched the sampled target outcome. A minimum of 75% was specified as the adherence criterion. The reported agreement of 97–100% in completed live episodes described how closely the simulator followed its instructions. It was not the percentage of questions answered correctly.

The following measures were recorded: pre-test to post-test change, agreement with the simulator’s hidden learner state, demonstration contradicted by the post-test, matches to assigned misconceptions, prerequisite violations, repeated questions, token use, cost, and latency by role.

#### Lecture 8 comparison of course maps and practice sessions

The Lecture 8 study was conducted in two stages. The same file, `COMP7608B_Lec08.pdf`, was prepared under four Expert prompt styles. All four runs were completed. Human review of the maps was still pending. Three published maps were then used in a separate 27-condition comparison of Tutor and Assessing prompts. The Baseline map was excluded from this live comparison. The earlier offline comparison with scripted answers is reported in Section 5.4.

The six Tutor and Assessing templates were based on the built-in v2 prompts. The configured model and provider-default temperature were used throughout. For each agent, only the added planning or assessment instruction was varied. Shared instructions, required output fields, and program checks were held fixed. The same response and question-selection instructions were stored across Tutor templates, although the latter instruction was not used during Tutor runs. Feedback and learning-memory instructions were held fixed across Assessing templates.

| Agent | Saved template | Added emphasis |
| :--- | :--- | :--- |
| Tutor | Tutor - Learner-focused | Prioritize the learner's current state and recent answers, including a supported recent mistake, uncertainty, or weakness. |
| Tutor | Tutor - Prerequisite-focused | Prioritize a coherent path through the prerequisite graph and eligible foundations for the learner's goal. |
| Tutor | Tutor - Balanced | Consider the supplied scores and factors for need, uncertainty, review urgency, recent performance, and the learner's goal. |
| Assessing | Assessing - Correctness-focused | Award rubric points only for evidence in the answer; do not infer unwritten reasoning. |
| Assessing | Assessing - Context-aware | Apply the key and rubric while considering hints, earlier attempts, and contradictions in the feedback; do not treat response time as proof of understanding. |
| Assessing | Assessing - Conservative | Avoid unsupported inferences and identify uncertainty when an answer is ambiguous, incomplete, or inconsistent with earlier evidence. |

Four Expert tasks were affected by the alternative prompts: concept extraction, proposal of prerequisites, review of links, and lesson planning. Conditions were listed in the Rules style, decisions were ordered in the Procedural style, and examples were supplied in the Exemplar style. The differences and the saved Tutor and Assessing instructions are documented in [Appendix B](#appendix-b-prompt-instructions).

**First-stage Expert evaluation (`COMP7608B_Lec08.pdf`).** All four styles were applied to the same 73-page Lecture 8 file, from which 73 passages were extracted (SHA-256 prefix `d16b66702316`). In each run, `openai/gpt-6-luna` was accessed through OpenRouter at the provider’s default temperature. Local `bge-m3` embeddings were used for passage search, and Poppler (`pdftoppm`) was used to recover slide images. The same output fields and checks were required across all four styles.

In an early Rules run, a ten-word bullet was expanded into a lesson whose claims were unsupported by the slide. In early Procedural runs, nearly every proposed prerequisite was rejected. The prompts were revised so that sufficient material for a lesson and direct use of a prerequisite had to be established from the pages. Passage matching and recovery after failed checks were also corrected. Because both the prompts and the checks were revised during development, the differences between completed runs could not be attributed to wording alone.

All generated lessons and starter questions were accepted by the automatic checks in the four completed runs. With Rules, 52 concepts and 16 prerequisites were produced. With Baseline, 77 concepts and 8 prerequisites were produced from the same lecture. The cost recorded for Rules was about 44% lower. Additional links could have clarified the order of practice, but an unnecessary prerequisite could also have delayed access to a topic.

| Expert prompt | Concepts | Prerequisite links | Lessons passing checks | Cost (US$) |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 77 | 8 | 77 of 77 | 0.6108 |
| Rules | 52 | 16 | 52 of 52 | 0.3409 |
| Procedural | 58 | 14 | 58 of 58 | 0.3664 |
| Exemplar | 57 | 11 | 57 of 57 | 0.3840 |

The run IDs, repairs, timings, token counts, and examples from the generated maps are recorded in [Appendix C](#appendix-c-lecture-8-run-records).

*Limits of the comparison.* Only one completed run was available per style. Source support, lesson scope, and answer keys were checked automatically. Coverage of the lecture and the validity of each prerequisite had yet to be assessed by a human reader. In particular, the maps still needed to be checked against `COMP7608B_Lec08.pdf` for missing concepts and for distinct concepts that had been merged.

**Tutor and Assessing evaluation (27 planned conditions).** Three published maps were crossed with three Tutor templates and three Assessing templates (3 × 3 × 3). The Rules (`33aaf382`), Procedural (`5905514c`), and Exemplar (`96e02e2c`) maps were included. Baseline (`21568e68`) was evaluated only in the first stage. Common settings were specified for all conditions.

| Setting | Value |
| :--- | :--- |
| Material | `COMP7608B_Lec08.pdf`, the published Workbench generation for that Expert style |
| Concepts | The first 6 concepts in published order were selected in every condition. |
| Activities per learner | 12 |
| Learners | Four profiles were scheduled for each of 27 conditions, giving 108 planned episodes. A retry belonged to the same learner and condition. |
| Student simulator | Belief-based pilot |
| Agent model | `openai/gpt-6-luna` (backend default) for Expert, Tutor, and Assessing |
| Student model | `openai/gpt-oss-120b`, a different model from the agents |
| Held-out exams | No held-out pre-test or final test was administered. |
| Temperature | Provider default |
| Execution | Up to 4 conditions were run at a time. One retry was allowed per failed learner. |

Simulated answers were written by a separate model so that the Assessing agent was given responses produced by another model. Multiple selections, filled blanks, and written answers were permitted. An item was counted as correct only when the complete set was selected, every blank was filled correctly, or full rubric credit was awarded. Partial scores were retained for analysis.

The first 6 concepts were selected in published order from each map. Basic concepts had been placed first, and links in these maps connected early concepts to much later ones. No prerequisite link was therefore present within any selected sample. Eligibility checks were applied, but no link within the sample could be followed by the prerequisite-focused Tutor. Activity choice, practice after mistakes, hint use, and marking could be compared. Differences in prerequisite sequencing could not be assessed.

All 12 activities were completed in a preliminary run with one novice. The run was excluded from the 27-condition comparison and was documented separately in Appendix C.

For each learner episode, the number of completed activities, correct answers, hints, and demonstrated levels was recorded. Rule violations, calls, latency, and cost were also recorded. No pre-test or post-test was administered in this study. By 21 November, first-attempt results had been saved for all 108 planned episodes: 85 were completed and 23 were marked as failed. These counts describe the first attempts only. A comparison of outcomes across prompt conditions requires retries to be matched to their original episodes so that a learner is counted once.


### 5.4 Results

In the Lecture 2 study, an *episode* was one simulated learner’s session under a given configuration. A *batch* could contain episodes for several learner profiles, which is why more than one row in Table 2 carries the same run ID. Selected episodes are shown below. The adaptive Tutor and the grounded, utility, and weighted prompts were used with `openai/gpt-6-luna` at temperature 0.2. These short episodes were used to examine the behaviour of the tutoring loop. No comparison with the other 26 prompt combinations was made in these live sessions.

| Run | Setup | Profile | Pre → post | Change | State match | False demonstration | Violations | Cost (US$) |
| :--- | :--- | :--- | :--- | :---: | :--- | :--- | :--- | :---: |
| `722a04b0` | 5 concepts, 3 questions | Intermediate | 0.67 → 0.33 | −0.33 | F1 0.14 | — | 0 / 0 / 0 | 0.0066 |
| `722a04b0` | same | Misconception-prone | 0.27 → 0.20 | −0.07 | F1 0.20 | — | 0 / 0 / 0 | 0.0072 |
| `722a04b0` | same | Hint-dependent | 0.27 → 0.47 | +0.20 | F1 0.13 | — | 0 / 0 / 0 | 0.0074 |
| `64f8c6f7` | 5 concepts, 2 questions | Novice | 0.13 → 0.20 | +0.07 | state accuracy across concept–difficulty pairs 0.93, macro-F1 0.24 | none estimated | 0 / 0 / 0 | 0.0065 |
| `23f5acb8` | 7 concepts, 4 questions | Novice | 0.33 → 0.48 | +0.14 | — | — | 0 / 0 / 0 | 0.0052 |
| `23f5acb8` | same | Intermediate | 0.86 → 0.95 | +0.10 | — | 0.00 | 0 / 0 / 0 | — |
| `23f5acb8` | same | Misconception-prone | 0.86 → 0.76 | −0.10 | — | 0.00 | 0 / 0 / 0 | 0.0071 |
| `5935f369` | 7 concepts, 2 questions, Workbench | Novice | 0.33 → 0.62 | +0.29 | — | 0.00 | 0 / 0 / 0 | 0.0047 |

*Table 2. Selected Lecture 2 episodes. Pre-test and post-test scores were mean rubric scores on a scale from 0 to 1. The change was calculated before rounding, so it may differ slightly from the difference between the two displayed scores. A dash indicates that a value was not reported in this table. The three violation counts refer, in order, to prerequisite violations, invalid progress updates, and repeated questions.*

Across all 36 completed live episodes, no prerequisite violation, invalid update, or repeated question was recorded. The failed novice episode in `722a04b0` was retried separately. One hint-dependent episode in `2c9c90e9` was stopped when its budget was reached.

In the offline study, 216 episodes were completed with scripted answers (3 Expert styles × 3 Tutor styles × 3 Reviewer styles × 4 profiles × 2 repeats). A further 24 baseline episodes were completed. No workflow failure was recorded. Execution of each condition was checked, but learning was not measured in these scripted runs.

The adaptive Tutor was used throughout the live Lecture 2 study. The fixed-order Tutor and the Tutor without memory were checked offline only. Their relative effects on progress in live sessions were therefore not established.

### 5.5 Human check of model judgments

Human review was required for two judgments: whether a lesson was supported by its cited pages and whether a mark was supported by the student’s writing. Three criteria were specified for that review.

1. Each claim in a lesson or explanation had to be supported by the cited pages.
2. The stored key had to be recoverable from those pages alone, and no other option could be equally well supported.
3. Each rubric score had to be supported by the response. Any words cited as evidence of a misconception had to be quoted directly from it.

Of 36 lesson packs from a 12-concept unit, 10 were flagged through automatic screening with `gpt-6-luna`, `gemini-2.5-flash`, and `bge-m3` similarity (`review-packet-002.md`). The 36 units counted here were teaching materials, whereas the 36 units counted in Section 5.4 were completed learner sessions. A flag identified material for inspection. Whether the flagged material contained an error had not yet been established by human review. `[TEAM TODO: two members should score 20–30 source reviews and 20–30 marked answers from the saved call files, report the rate of agreement with the model, and give one or two disagreements.]`

### 5.6 Interpretation and limitations

In the short Lecture 2 episodes, only two to five practice questions were assigned across a unit of five to seven concepts. The separate test score was calculated from the mean rubric credit across test items. On a 15-item test, a change from zero to full credit on a single item would move that mean by about seven percentage points. A small change in the mean could therefore reflect performance on just one question. More direct evidence of Tutor behaviour was obtained from the activity records. A missed topic was revisited, prerequisites were respected, and the topic was retained at *developing* after one qualifying answer.

Agreement with the simulator’s hidden state was measured for each concept at each difficulty, including levels that had received no practice. Two summaries were used. Overall accuracy was the proportion of concept–difficulty pairs given the same state by LearnLoop and the simulator. Macro-F1 was calculated separately for *unassessed*, *developing*, *demonstrated*, and *review due*, then averaged with equal weight for each state. A state absent from both sets of labels was assigned an F1 of zero in this calculation. In run `64f8c6f7`, an overall accuracy of 0.93 and a macro-F1 of 0.24 were recorded. The high overall accuracy therefore did not establish that each of the four states had been identified reliably.

Misconception precision was calculated at the concept level. Concepts for which the Reviewer had flagged a misconception during practice were compared with concepts for which a misconception was still recorded in the simulator at the end of the episode. Where precision could be calculated, it was zero: none of the flagged concepts was in that final set. The wording of the Reviewer’s explanation was not compared with the wording of the simulated belief by this metric. Whether an individual explanation was justified by the student’s answer would require a separate human reading.

Two observations about demonstration were recorded. In an early one-concept trial, a topic was marked as demonstrated even though the learner’s overall post-test score was lower than the pre-test score. A separate measure, the *false-demonstration rate*, was calculated from individual concept–difficulty pairs. Among the pairs marked as demonstrated, it was the proportion for which less than full credit was earned on the corresponding post-test item. A rate of 0.00 was recorded in the later runs `23f5acb8` and `5935f369`. The number of observations was too small for the two-answer rule to be validated as a measure of lasting understanding.

The Lecture 2 evaluation was limited to a single lecture, one generation model, and simulated students with assumed learning and hint rates. The findings were therefore limited to system behaviour under those conditions. Learning gains for real students could not be established without a separate study.

---

## 6. Contributions and Attribution

| Member | Contribution |
| :--- | :--- |
| Member 1 | `[TEAM TODO]` |
| Member 2 | `[TEAM TODO]` |
| Member 3 | `[TEAM TODO]` |
| Member 4 | `[TEAM TODO]` |

The application was built with FastAPI, Next.js, and SQLite. COMP7608B lecture materials were used as course sources. Local passage search was supported by BAAI BGE-M3 [7], and generation models were accessed through OpenRouter. Software versions are listed in [Appendix D](#appendix-d-software-and-versions).

Stand-in clients were used for model calls and passage search during software tests and offline evaluation. In runs labelled `workflow_only`, execution of the steps was checked. Model quality could only be assessed with live responses.

Several proposal items were omitted or replaced. LangGraph and Docker were not used in the delivered local setup. Multi-user accounts, rewards, optical character recognition, and a session-wide dollar cap were not implemented. New questions could be requested through the Tutor workflow. A route for the Reviewer to request a follow-up question was not implemented.

---

## AI-Use Declaration

`[TEAM TODO: name each tool and model, for example Cursor and ChatGPT, and state what each one helped with.]`

AI assistance was used to draft parts of the API and student pages, develop tests and worker locking, and prepare evaluation logs. It was also used to organize and edit the report against the course guideline. The progress rules, prompts, tests, and reported figures were checked by group members against project runs. Redacted project prompts were designated for inclusion under `ai_use/` in the submission ZIP. `[TEAM TODO: state here if any early chats were not saved.]`

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

## Appendix A. Recovery checks

| Failure | Detection | Response | Message to the user | Evidence |
| :--- | :--- | :--- | :--- | :--- |
| Provider timeout or server error during preparation | HTTP 408, 425, 429, or 5xx, or a 90-second timeout | Up to 3 client retries and 4 worker attempts were allowed, with 20 seconds between worker attempts. Completed sections were retained. | “Processing was interrupted. Retrying automatically in 20 seconds.” or a Retry button | `test_section_review_resume_only_reprocesses_failed_section` |
| Unsupported lesson or question | An unknown page identifier was returned, a source check failed, or the key was rejected by the solver. | Two repairs were allowed before the item was held for review. | The gap was shown and the key was withheld. | `test_semantic_failure_blocks_graph_publication` |
| Duplicate submission or outdated learner record | The `operationId` and `expectedLearnerVersion` were checked. | The original receipt was returned for a repeated operation. HTTP 409 was returned for a conflict or stale version. | The page was reloaded and the answer was counted once. | `test_assessment_waits_for_explicit_next_and_retry_keeps_evidence_once` |
| Interruption while a mark was being saved | The database transaction was not committed. | The mark, learner version, and event were rolled back together. | The run could be retried with the earlier progress record intact. | `test_assessment_commit_failure_rolls_back` |
| Worker interruption or expired lease | The lock file was released by the operating system after interruption. The lease was limited to 1,800 seconds. | The job could be resumed by the next worker. A second live worker was prevented from taking it. | Work was resumed from the last checkpoint. | `test_expired_job_lease_is_reclaimed` |
| Missing API key or stop requested by the user | Checks were made before model calls and between steps. | The run was paused before a call or stopped with completed work retained. | “Configure the generation model, then resume.” or “Stopped by user. Saved work is retained.” | `runtime/workflows.py`, `runtime/worker.py` |
| Simulated episode at its call budget | The limits of 64 calls or 250k tokens were checked before the next call. | The episode was stopped and usage to that point was retained. | The episode was marked `budget_exhausted`. | Live run `2c9c90e9` and budget tests in the harness |

---

## Appendix B. Prompt instructions

**Differences in the saved prompts.** Four parts of the Expert’s work were varied: section concept extraction, relationship analysis, relationship review, and curriculum planning. The variants were defined in `agents/expert/prompts_variants.py` and the baseline in `agents/expert/prompts.py`. One organization style was selected in each of the three saved Expert templates. No additional text was entered in their three editable prompt fields.

| Expert setting | Exact examples of distinctive instructions |
| :--- | :--- |
| Baseline | The production organization prompts in `prompts.py` were used without the additional checklists, procedures, or examples. |
| Expert · Rules | Constraints were grouped under `Evidence rules`, `Granularity rules`, `Prerequisite rules`, and `Scope fidelity rules`. Enough evidence was required for a short lesson, example, and two basic questions. Limits were set on splitting goals. Each prerequisite had to be used directly in the later concept, and `teaches` was limited to one sentence supported by the summary. A final self-check was requested. |
| Expert · Procedural | The decisions were ordered from `Step 1` to `Step 7`. The size of each concept and the direct use of each prerequisite were checked. Redundant links were removed, and teaching scopes were drafted in layer order with one brief, summary-supported `teaches` sentence. |
| Expert · Exemplar | Contrasting examples from introductory statistics were supplied. Suitable concept size, thinly supported goals, synonyms, incorrect citations, and cycles were illustrated. The prerequisite `mean` → `variance` was distinguished from the related pair `mean`–`median`, and claims exceeding a lesson’s `teaches` scope were illustrated. |

The following **Learning plan** instructions were saved in the Tutor templates. The shared final instruction was omitted from these quotations.

**Tutor - Learner-focused**

> Choose one activity from the supplied eligible candidates. Prioritize the learner's current state and recent answers. Prefer an activity that addresses a recent mistake, uncertainty, or weak performance when the supplied record supports it. Do not invent learner history. Return the selected candidate identifier and a concise reason grounded in the record.

**Tutor - Prerequisite-focused**

> Choose one activity from the supplied eligible candidates. Prioritize a coherent path through the prerequisite graph. Prefer an activity that strengthens an eligible foundation for the learner's goal, while considering the supplied learner state. Use only the supplied graph and candidate information. Return the selected candidate identifier and a concise reason grounded in the learning path.

**Tutor - Balanced**

> Choose one activity from the supplied eligible candidates. Consider the supplied scores and factors, including learning need, uncertainty, review urgency, recent performance, and the learner's goal. Select the candidate that best addresses the overall learning need. Do not invent scores. Return the selected candidate identifier and a concise reason grounded in the supplied factors.

The following **Answer analysis** instructions were saved in the Assessing templates. The shared final instruction was omitted from these quotations.

**Assessing - Correctness-focused**

> Assess the submitted answer against the supplied answer key and rubric. Award each rubric point only when the student's answer provides the required evidence. Do not infer reasoning the student did not write. Quote the student only when the words appear in the answer. Mark uncertainty when the available evidence does not support a reliable judgment.

**Assessing - Context-aware**

> Assess the submitted answer against the supplied answer key and rubric. Consider supplied hint history, earlier attempts, and contradictions when explaining your feedback. Do not let a hint or earlier attempt change whether the current answer matches the key or justify unsupported rubric credit. Treat response time as context, not proof of understanding. Quote only words present in the student's answer and mark uncertainty when evidence is insufficient.

**Assessing - Conservative**

> Assess the submitted answer against the supplied answer key and rubric. Award a rubric point only when the answer clearly supports it. When the answer is ambiguous, incomplete, or inconsistent with earlier evidence, state the uncertainty rather than inferring the student's reasoning or asserting an unsupported misconception. Explain what evidence is missing and quote only words present in the student's answer.

In the shared final instruction, use was restricted to the supplied context, learner and course content was to be treated as data, and a structured reply was required. The additional instructions were applied alongside the built-in prompt and existing program rules.

---

## Appendix C. Lecture 8 run records

### Early runs and revisions

*Initial failures and revisions.* In the first trials, only the Baseline run (`21568e68`) was completed. The other styles were held for review.

- **Rules.** Incorrect passages were cited in the first run (`8c497bae`, 110 s, US$0.0278). After the section prompt was revised, 63 of 67 lessons were accepted (`834a3ebc`, 687 s, US$0.5176). A ten-word bullet was expanded into a lesson on `tool-argument-filling`. The objective for `read-model-card-scores` was also set beyond the evidence available in its cited pages. As a result, both the proposed objective and the source requirement could not readily be satisfied.
- **Procedural.** A link was tested by asking whether a basic question about B could be answered without understanding A. Almost every proposed prerequisite was rejected under this test. Only one link was retained in `e0590042` (60/61 lessons, US$0.4287) and two in `1b06c246` (56/57 lessons, US$0.3873). A nine-word sentence was treated as a separate goal, `known-solution-validation`, despite insufficient evidence for a lesson. In `d94a1774` (US$0.0297), page 48 was cited as `s48` when the available labels were `s40..s47`. Retry limits were reached in later runs after problems with lesson scope, questions, or the required output format (`218f6bfd`, 47/50 lessons, US$0.3288, and `f1d52dcc`, 55/58 lessons, US$0.4665).
- **Exemplar.** A cycle was proposed after nine of ten sections had been completed. The run was stopped at the `cyclic_graph` error, and the section was not retried (`92972b4b`, 102 s, US$0.0235).

Five revisions were made to the teaching instructions, the way evidence was supplied, and the handling of failed checks.

1. All three alternative prompts were revised. Sufficient material for a lesson, a direct reason for each prerequisite, a map without cycles, and a short objective supported by the concept summary were required (`prompts_variants.py`).
2. Passages were numbered within each section. The graph check was moved inside the existing retry step so that a rejected map could be corrected (`analysis.py`, `grounding.py`).
3. After a source or scope check failed, the rendered slide could be supplied on the next attempt. Saved slide transcriptions were reused on subsequent attempts (`materials.py`).
4. One additional correction was permitted for a question or an output-format error. The existing limit on full lesson revisions was retained.
5. Feedback from an earlier failed draft was excluded from slide-transcription requests and independent reviews (`workflows.py`).

### Completed Expert runs

*Completed first-stage runs.* Every lesson and its starter questions were accepted by the automatic publication checks in the four completed runs. The number accepted, size of each map, cost, and observations were recorded below.

| Expert template (run ID) | Automated pass (lessons) | Concepts / topics | Prerequisites / related | Layers (B / I / A) | Slide recoveries / repairs | API calls & tokens (in / out) | Time & cost | Human review: supported concepts | Human review: justified prereqs | Example observation |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- | :--- | :---: | :---: | :--- |
| Baseline (`21568e68`) | 77 / 77 (0 flagged) | 77 / 15 | 8 / 36 | 70 / 6 / 1 | 5 / 39 | 527 calls (3.70M / 395k) | 875 s, US$0.6108 | `[TODO]` | `[TODO]` | The most concepts (77), calls, and cost were recorded under Baseline. Eight prerequisites were proposed, including `Token precision` → `Token F1`. One advanced goal was identified (`Version and reuse accepted proposers`). |
| Expert · Rules (`33aaf382`) | 52 / 52 (0 flagged) | 52 / 10 | 16 / 23 | 36 / 14 / 2 | 1 / 16 | 304 calls (2.02M / 229k) | 530 s, US$0.3409 | `[TODO]` | `[TODO]` | The fewest concepts, shortest preparation time, and lowest cost were recorded for Rules (44% lower cost than Baseline). Sixteen prerequisites were proposed, with 14 intermediate and 2 advanced concepts. Links were proposed from `Accuracy/exact match` to `MMLU`, `GSM8K`, and short-answer tasks. |
| Expert · Procedural (`5905514c`) | 58 / 58 (0 flagged) | 58 / 10 | 14 / 30 | 46 / 12 / 0 | 2 / 21 | 357 calls (2.15M / 265k) | 619 s, US$0.3664 | `[TODO]` | `[TODO]` | The concepts were grouped into 10 topics. Fourteen direct prerequisites were proposed, including `Token Precision, Recall, and F1` → `skill-router precision and recall`. No advanced concepts were assigned in this run. |
| Expert · Exemplar (`96e02e2c`) | 57 / 57 (0 flagged) | 57 / 12 | 11 / 22 | 46 / 10 / 1 | 7 / 23 | 366 calls (2.21M / 276k) | 691 s, US$0.3840 | `[TODO]` | `[TODO]` | Concepts were assigned across all three layers (46/10/1), including the advanced goal `Using held-out proposals for a model-side screen`. Slide images were used to recover evidence for 7 lessons, the highest count among the four runs. |

### Tutor and Assessing pilot

A preliminary run (`34dd1895`) was completed before the grid using the Procedural Expert, Learner-focused Tutor, Correctness-focused Assessing template, and novice profile. All 12 activities were completed, 8 answers were marked correct, no hints were used, and 2 levels were demonstrated. No prerequisite violations, invalid updates, or repeats were recorded. The run required 104 calls and 398 s at a cost of US$0.0257. The same condition was scheduled for all 4 learners within the grid. The pilot was excluded from the count of 27 conditions.

---

## Appendix D. Software and versions

The backend was built with FastAPI 0.128.4, Uvicorn 0.40.0, SQLAlchemy 2.0.46, Alembic 1.20.0, Pydantic 2.12.5, pydantic-settings 2.12.0, sqlite-vec 0.1.9, httpx 0.28.1, pypdf 6.11.0, filelock 4.2.8, and jsonschema 4.26.0. Next.js 16.4.2, React 19.3.0, Zod, react-markdown, and KaTeX were used in the frontend. Slide images could be rendered with Poppler’s `pdftoppm` when installed. Models were accessed through OpenRouter and Ollama, and BAAI `bge-m3` [7] was used for passage search. COMP7608B Lecture 2 was used for the earlier live evaluation.

---

## Working notes for PDF export

Remove these working notes before submission.

- [ ] Fix the 9 failing tests (`test_organization.py`, `test_slide_evidence.py`, `test_tutor_chat.py`) so the tagged tree passes. Last reported count: 302 passed, 9 failed, 311 collected.
- [ ] Complete the human-review columns in Appendix C. Use the finished grid to report the 27 conditions in Section 5.3, including failures and retries.
- [ ] Run the live baseline in Section 5, or state that it was checked offline only.
- [ ] Complete the human check of source reviews and marking.
- [ ] Fill in the git version, each member’s contribution, and the AI-use notes.
- [ ] Export the PDF and follow the README on a clean machine.
- [ ] Confirm which sample files are included in the ZIP.

### Tables for pending comparisons

Use the following table when reporting the 27-condition comparison in Section 5.3.

| Cell | Activities completed | Correct answers | Demonstrated levels | Violations | Cost (US$) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 27 cells × 4 learners | `[TODO]` | `[TODO]` | `[TODO]` | `[TODO]` | `[TODO]` |

For the live baseline comparison in Section 5.4, run the adaptive, fixed-order, and memory-free conditions on the same release of 5 or 7 concepts. Use four profiles, at least three repeats, and 8–12 questions. The estimated cost is under US$0.50. Fill the table if the comparison is completed.

| Condition | Mean gain (with spread) | Topics demonstrated at the target | Ineligible or repeated actions | False demonstration | Mean cost (US$) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| LearnLoop, adaptive | `[TODO]` | `[TODO]` | `[TODO]` | `[TODO]` | `[TODO]` |
| No memory of earlier sessions | `[TODO]` | `[TODO]` | `[TODO]` | `[TODO]` | `[TODO]` |
| Fixed order along the prerequisite chain | `[TODO]` | `[TODO]` | `[TODO]` | `[TODO]` | `[TODO]` |
