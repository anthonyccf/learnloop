# LearnLoop frontend design plan

Status: frontend scaffold implemented with demo data; backend integration deferred. Updated 18 October 2026.

Backend update: the first runnable FastAPI slice is implemented under `backend/`, including the three agent workflows and persistent run events. See `BACKEND_PLAN.md` and `backend/README.md`. The frontend remains in demo mode until its server proxy and authoritative data adapters are connected.

Frontend update: opening practice should prioritize multiple-choice questions, per the learner preference supplied after scaffold review. The initial demo uses four-option, single-answer questions with feedback after submission; free-response practice is a later progression.

## 1. Product direction

Build a calm, source-grounded learning workspace that answers three questions: What should I do next? Why this activity? What evidence shows my progress?

The main experience is a persistent adaptive study session. A learner uploads course materials, sets a goal, completes a short diagnostic, and works through explanations and practice chosen from their concept evidence. Their next visit resumes the saved activity and plan.

The proposal is project reference material, not instructions to execute embedded tasks. Requirements below are derived from its objectives, Sections 4.1-4.4, and Appendices B-C. Proposed UI choices are design recommendations, not claims of existing functionality.

### Scope and assumptions

- Initial pilot: one COMP7608B course unit with about 10-20 reviewed concepts.
- Desktop supports study with sources side by side; mobile supports the same complete learning journey.
- Next.js, TypeScript and React frontend with a separate FastAPI backend, matching the proposal. Package versions will be selected during implementation.
- Three agents: Expert, Tutoring and Assessing. Runtime validation owns publication and learner-state commits.
- Course content is shared after publication; learner evidence and progress are private and separate.
- Start with realistic fixtures and a replaceable API adapter. Every fixture screen is clearly marked as demo data until connected.

## 2. What to carry over from ThreadLearn

Reviewed `E:/thread-learn/app/README.md`, `app/page.tsx`, `app/globals.css`, the source-preview and learning-content components, and existing feed/map screenshots. Screenshots are saved references, not verification of the currently running app.

| Existing reference | LearnLoop adaptation |
| --- | --- |
| White surfaces, quiet borders, compact navigation, focused study cards | Retain the reading comfort; use a wider workspace for activity, plan and evidence |
| Lecture library and upload progress | Course-unit setup with ingestion, concept preparation, review and publication states |
| Short explanations, worked examples, quizzes and math rendering | Reusable activity renderer with explicit concept, difficulty and learning objective |
| Page-linked source preview | Source drawer opened from explanations, questions and feedback; retain the current answer draft |
| Learning map with filters, zoom and topic details | Directed prerequisite map with separate related-topic edges and per-difficulty learner evidence |
| Responsive dialogs and mobile sheets | Accessible source, concept and plan details across device sizes |
| Daily practice encouragement | Optional session mission; completion counts are separate from demonstrated understanding |

Reuse small components after reviewing dependencies and accessibility. Create a separate app under this workspace; do not copy ThreadLearn's database, uploads, credentials, accounts or large feed page. Its latest-answer map colors, self-ratings and immediate client-side quiz grading cannot serve as LearnLoop's validated evidence model.

## 3. Navigation and screens

Desktop sidebar: Today, Learn, My understanding, Materials, Progress. My understanding is the central knowledge-graph view. Course selector above the navigation; account/settings below. Course preparation and run inspection are separate staff views.

| Screen / proposed route | Main content and primary action |
| --- | --- |
| Today `/` | Current goal, Resume/Start session, recommended next concept with a short reason, reviews due, recent saved progress |
| Course setup `/courses/new` | Name a unit, upload materials, set target difficulty and goal, follow preparation progress |
| Learn `/courses/[courseId]/learn` | Concept-specific MC practice, hints, source links, feedback, follow-up guidance and resumable sessions |
| Session summary `/courses/[courseId]/learn/summary` | Before/after concept state, retained answers, hint use, independent checks and an eligible next concept |
| Diagnostic `/courses/[courseId]/diagnostic` | Brief concept coverage check; explain that this initializes evidence and does not establish demonstrated status by itself |
| My understanding `/courses/[courseId]/map` | Two views of the course graph: course structure and personal understanding; concept details connect assessment evidence to source materials |
| Materials `/courses/[courseId]/materials` | Documents, page/source preview, processing state and generated resources grouped by concept |
| Progress `/courses/[courseId]/progress` | Four-state concept summary, difficulty table, assessment history, misconceptions and review schedule |
| Course review `/manage/courses/[courseId]` | Staff inspect flagged concepts, prerequisite edges, sources, questions and rubrics before publication |
| Run inspector `/manage/runs/[runId]` | Staff inspect structured actions, validation outcomes, retries and operational measurements |

For mobile, use five labeled bottom destinations: Today, Learn, My understanding, Materials, Progress. Place course switching in the header and staff pages in the account menu. Preserve useful URLs, selected course and filters across navigation. The current single-course scaffold uses `/map`; course-scoped paths remain the integration target.

## 4. Main learning workspace

Desktop layout: 208px sidebar, flexible main column with an approximately 720px reading measure, optional 320px context panel. Start with the context panel closed at narrower desktop widths.

```text
+---------------+------------------------------------+-----------------------+
| LearnLoop     | COMP7608B / Optimization            | Session plan          |
| Course picker | Goal: explain gradient descent     | Current: gradient     |
|               |                                    | descent               |
| Today         | Gradient descent    Intermediate   | Next: check evidence  |
| Learn         | Why this activity?                 |                       |
| Concept map   | Previous answer missed step size.  | Your evidence         |
| Materials     |                                    | Basic: demonstrated   |
| Progress      | Question / example / explanation   | Intermediate:         |
|               | [Course slide 12]                  | developing            |
|               |                                    | Advanced: unassessed  |
|               | [Your answer...................]   |                       |
|               | [Hint]              [Submit answer]| Sources / History     |
+---------------+------------------------------------+-----------------------+
```

Wireframe labels illustrate a fixture scenario. The next activity remains provisional until the runtime assigns it.

### Activity interaction

1. Show the concept, activity type, difficulty, objective and a concise, source-supported reason for the selection.
2. Explanations and worked examples lead into practice. Reading or completing an explanation never changes demonstrated status on its own.
3. The answer editor supports plain text and mathematical notation. Keep input when opening sources, requesting a hint, reconnecting or receiving a validation error.
4. Requesting a hint records hint use for this attempt. Explain this briefly at the hint control, without penalizing or shaming the learner.
5. Submit once; show assessment progress. Do not expose reference answers, correct-option indexes or private grading rubrics in the active question payload.
6. Display rubric-based feedback, supporting sources and misconceptions. Separate assessed feedback from a pending progress save.
7. Confirm the concept's updated status only after the backend acknowledges its validated commit. If inconclusive, say that more evidence is needed.
8. Offer Continue, review an explanation, or End session. Show the next activity once assigned; if preparation pauses, retain the last saved state.

Use a concise activity status such as Preparing activity, Waiting for your answer, Checking response or Progress saved. Expandable "Why this activity?" shows a decision summary and evidence references, not private chain-of-thought.

## 5. Progress semantics

Use these exact underlying states with approachable labels. Color is always paired with text and an icon.

| Backend state | UI label | Visual role / explanation |
| --- | --- | --- |
| `unassessed` | Not assessed | Neutral outlined circle; insufficient validated evidence |
| `developing` | Developing | Blue partial-circle; more independent evidence needed |
| `demonstrated` | Demonstrated | Green check; required independent evidence validated |
| `review_due` | Review due | Amber clock; reassessment needed, earlier evidence retained |

- Overall state is relative to the concept's target difficulty. Always show that target next to the state.
- Detail panel displays separate Basic, Intermediate and Advanced evidence. Lower-level success does not demonstrate a higher target.
- Two rubric-meeting responses to distinct questions at the target difficulty are required, without hints or unresolved contradictions. One correct answer should say "One qualifying response recorded" when the backend confirms it.
- Hint-assisted or partial performance may support Developing; slow responses alone cannot demonstrate understanding.
- A demonstrated concept becomes Review due after seven days under the proposal's rule. Backend supplies review timing; the browser does not invent state transitions.
- Later contradictions retain earlier evidence. Show the validated result and a short reason for review or remediation.
- Readiness is a separate field from concept state. A prerequisite-blocked concept displays the unmet prerequisites and a route to the suggested preparatory activity.
- No arbitrary mastery percentage. Show counts such as "6 of 14 concepts demonstrated at their targets" and dated evidence instead.
- Optional encouragement or mission completion does not change evidence, readiness or concept status.

## 6. Course setup and knowledge map

Setup journey: upload documents -> confirm the selected unit and goal -> extract source passages -> prepare concepts/resources -> inspect flagged items -> publish course version -> diagnostic -> first session.

Show real reported preparation stages and counts, not fabricated progress percentages. Each failed document has a useful retry action. Unsupported resources and prerequisite cycles remain flagged until resolved. Learners can study a published version; draft resources stay in the preparation view.

For 10-20 concepts, a stable directed graph is sufficient. Draw arrows for prerequisites and dashed lines for related topics, with a legend. Label nodes by default. Selecting a node opens the difficulty evidence, prerequisite readiness, source references and recommended action. Provide search, fit, zoom, keyboard selection and an equivalent semantic list. Browsing a locked concept is allowed; starting an invalid activity is blocked by the backend.

### My understanding: course structure and learner evidence

Make the graph a primary way to explore understanding within course materials. It presents evidence-backed estimates, not a direct measurement of everything the learner knows. Use ThreadLearn's connected-topic browsing as inspiration; its semantic similarities or latest-answer colors must not become prerequisite rules or demonstrated-understanding claims.

- **My understanding (default):** overlay the four learner states on the shared graph. Basic, Intermediate and Advanced controls change the displayed evidence level. Show state counts across the whole unit, labeled by the selected difficulty. Counts are not a mastery percentage.
- **Course structure:** show a neutral shared concept graph with lecture labels, source references and relationships. Hide personal state filters, progress colors, learner history and recommendations in this mode.
- **Relationships:** solid directed edges mean prerequisite → next concept; dashed undirected edges mean related topics without required learning order. Highlight prerequisite edges connected to the selected concept. Include an explicit legend and readable prerequisite/related lists in details.
- **Browsing:** support concept search, material filter, state filter in personal mode, bounded zoom, reset zoom and a keyboard-accessible equivalent concept list. Keep nonmatching graph nodes dimmed for context; the list and match count show actual matches. Preserve concept, view and difficulty in the URL, including browser back/forward handling.
- **Readiness:** determine activity eligibility from prerequisites at their target difficulties, independently of the difficulty used to inspect the graph. A Basic or Advanced overlay must not accidentally change eligibility. The prototype uses Intermediate targets across the sample unit; production targets are concept-specific.
- **Concept detail:** display the selected difficulty's state and a plain-language reason; a three-level evidence matrix with independent and assisted counts; ideas to revisit; target-level assessment/review timing; prerequisites and related ideas; a source reference opening the relevant material passage; recent assessment records and a recommended next step.
- **Evidence history:** retain incorrect, hinted and independent attempts. Each new MC attempt records its question, selected answer, correctness, hint use and timestamp. Show the actual selected option rather than inventing a reflection. Repeated successes on one question count once toward the two-distinct-question rule. Do not invent detailed attempt logs for older snapshots that contain only summary counts.
- **Source integrity:** clearly label fixture passages, slide numbers and baseline evidence as illustrative. When integrated, the Expert Agent's reviewed source references replace fixture locations. Unsupported or flagged relationships must not appear as published prerequisite facts.
- **Next step:** every eligible concept opens its own MC practice. A blocked concept links to an unmet prerequisite; direct practice links also enforce readiness. Review-due concepts offer source review and independent reassessment.
- **Mobile:** keep graph scrolling within its panel; provide a selected-concept anchor and the equivalent list. Put full details below the graph. Preserve state labels/icons, keyboard focus and 44px control targets.

### Current frontend implementation and verification

`frontend/src/lib/learner-evidence.ts` supplies shared difficulty evidence for the map and Progress, source fixtures and typed assessment records. The demo provider appends MC history to the current browser session. Learner records remain separate from course concepts and relationships. Existing local sessions retain summary counts; missing detailed history is identified rather than reconstructed.

Acceptance checks: switching graph modes leaves the course topology unchanged; a difficulty switch changes displayed evidence without changing prerequisite readiness; an unassessed concept has no fabricated history; a review-due concept retains previous independent evidence; a source reference shows the selected concept's lecture and sample passage; a newly submitted MC answer appears in history; hints and repeated questions do not inflate qualifying evidence; completing two distinct independent questions updates the map and Progress consistently; deep links retain selected mode/concept/level; search with no matches has an explicit empty state; mobile has no page-level overflow.

This phase remains frontend-only. Production evidence, eligibility, review scheduling, source access and state commits remain backend responsibilities. The graph must never expose pseudo-students' hidden experimental knowledge states as learner evidence.

### Connected practice and session summaries (18 October update)

- The frontend now has two authored four-option questions per concept across all 12 sample concepts. The question bank is illustrative, not generated or verified against uploaded course PDFs.
- `/learn?concept=<id>` opens that concept; plain `/learn` resumes the most recently active concept. Invalid IDs offer a return to the graph. Unmet prerequisites offer foundation practice and browsing of the selected source instead of an invalid assessment.
- Each concept retains its own selected answer, question, hint use, assessment records and qualifying evidence. Moving between concepts or refreshing must not mix or lose those records.
- Wrong answers prompt explanation/source review and optional prerequisite review before another check of the same concept. Hinted success prompts an independent check. Independent success prompts a distinct second question. All feedback uses the local fixed answer key; this is not an autonomous agent integration.
- Ending a session saves it and opens `/learn/summary?concept=<id>`. The summary displays before/after state, only that session's submitted answers, distinct independent checks, hint use, and an eligible next recommendation. Starting another session preserves earlier concept evidence while opening a new summary slice.
- Recommendations first address unmet prerequisites. Once the current concept is demonstrated, prefer an eligible dependent, then an eligible review-due or developing concept. Both readiness and shared progress use the same concept records as My understanding.
- A later wrong answer to a demonstrated concept produces a local Review due outcome; earlier evidence is retained, and two fresh distinct independent successes resolve the conflict in this demo. Production policies still belong to the backend's validated runtime.
- Browser persistence uses `learnloop-practice-v3`; valid earlier v2 gradient-descent records migrate without deleting the older storage. Imported history stays separate from a new session's before/after attribution.
- Verification covers all 12 question sets, blocked direct links, independent versus assisted outcomes, duplicate submissions, concept switching, fresh session boundaries, persistence migration, and eligible dependent recommendations. Browser checks cover graph → practice → summary → graph, saved selections and responsive layouts.

## 7. Visual direction and accessibility

Suggested identity: a quiet study notebook with a restrained teal accent. Maintain ThreadLearn's readable cards and simple controls while giving LearnLoop its own identity.

- Canvas `#F7F8F6`, cards `#FFFFFF`, primary text `#172321`, secondary text `#53635F`, border `#DDE4DF`, primary action `#176B5B` with white text. Validate contrast during implementation.
- Status colors accompany labels/icons; they are not the only way to identify states.
- Use a local/system sans-serif stack initially. Body 16px, line height about 1.6, page heading 28-32px; math stays selectable and accessible.
- Spacing on a 4/8px scale, 12-16px card radius, restrained shadows. One primary action per active activity.
- Desktop uses labeled navigation. At tablet sizes, collapse navigation and move context into tabs. On phones, use a single reading column, bottom navigation and full-height details sheets.
- At 390px, all answer and source controls remain usable without page-level horizontal scrolling. Wide tables scroll within their container.
- Visible keyboard focus, semantic form labels, meaningful button names, focus restoration after dialogs, 44px touch targets, screen-reader status messages and reduced-motion support.
- Session time limits are absent by default. Runtime measures response time; the UI must not imply fast answers equal better understanding.

## 8. Frontend boundaries and API collaboration

Suggested structure for implementation:

```text
app/                   Next.js app and route layouts
components/layout/     Sidebar, course switcher, mobile navigation
components/learning/   Activity card, response editor, hints, feedback
components/evidence/   State badge, difficulty matrix, history
components/sources/    Source chips, passage viewer, PDF preview
components/graph/      Map, legend, accessible concept list
features/              Course setup, sessions, progress, staff review
lib/api/               Typed backend adapter and event handling
lib/contracts/         Shared transport schemas and domain types
fixtures/              Coherent demo courses and scenario outcomes
```

Agree contracts before connecting screens. These are proposed frontend needs, not existing backend endpoints:

| Capability | Required data / behavior |
| --- | --- |
| Course and ingestion | Course/document IDs, stages, issues, published version and permitted actions |
| Learner state | Concept targets, four-state values, per-difficulty evidence, readiness, review dates and record version |
| Start/resume session | Checkpoint, pending activity, plan version, last acknowledged operation and session status |
| Activity | ID, type, concept, difficulty, prompt/content, public source references and hint availability |
| Submit response | Stable operation ID, activity ID, expected version and response; server owns persisted hint use and response timing |
| Assessment result | Rubric feedback suitable for the learner, uncertainty, commit status and authoritative state/version |
| Sources | Authorized document/page/passage lookup; context needed to locate a citation |
| Run events | Ordered event IDs, current stage, retriable error and resumable cursor/checkpoint |

Use server events or polling behind one adapter; select transport with the backend team. On reconnect, fetch authoritative state before replaying actions. Disable duplicate submits and reuse the same operation ID for an uncertain retry. For stale versions, reload and reconcile; never overwrite newer learner evidence.

Draft answers may be retained in scoped browser storage with a clear saved-on-this-device label. Checkpoints and committed learning evidence live on the backend. Clear learner drafts on sign-out. Provider secrets and tool authorization remain server-side.

## 9. Required non-happy-path designs

Include empty course, no published unit, extraction failure, missing source, preparation requiring review, no eligible next concept, assessment uncertainty, failed save, stale record version, duplicate response retry, offline/reconnect, expired session and exhausted runtime budget.

Each state explains what happened, whether progress was saved and the available action. A failed save never displays a new committed concept status. An unavailable source is labeled unavailable rather than substituted with invented evidence. Retry exhaustion offers resume/retry when available and retains the checkpoint.

The staff run inspector can show agent roles, structured actions, validation rejections, proposed versus committed updates, latency, tokens and cost. Learner screens show only information that helps them study. A full 27-configuration experiment dashboard is deferred until the learning loop works.

## 10. Delivery sequence and completion criteria

| Phase | Deliverable | Review / completion criterion |
| --- | --- | --- |
| 1. Screen design | Today, Learn and Map wireframes, desktop/mobile; component and state inventory | A learner can identify their next action, source and progress evidence |
| 2. Visual prototype | Separate Next.js app, navigation, course selector, coherent fixture data, study/source/map interactions | Full demo journey works with clearly identified fixture data and no live model dependency |
| 3. Complete the loop | Diagnostic, answers, hinted attempt, feedback, two qualifying responses, review and resume scenarios | Distinct difficulty evidence, no unsupported status advances, preserved drafts and usable keyboard/mobile flows |
| 4. Backend integration | Typed adapters, preparation status, events, validated state commits and checkpoint resumption | Reload resumes the same pending activity; retries do not duplicate evidence; stale writes reconcile |
| 5. Staff tools and verification | Resource review, trace inspection, responsive and accessibility pass | Flagged resources stay unpublished; proposed/committed changes are distinguishable; error recovery is demonstrated |

Focused verification: the main journey; one success versus two distinct independent successes; hinted success; lower-than-target success; seven-day review; uncertainty; interruption/reload; duplicate retry; stale version. Verify real transitions in backend/integration tests; frontend tests check that the UI reflects returned authoritative outcomes. Inspect at desktop, tablet and 390px phone widths.

First implementation slice: Today + Learn + source drawer, using a 12-concept fixture course and a consistent learner history. Then implement the map and progress views against the same fixture model. This makes the core product reviewable before adding operational tools.

## 11. Deferred features

External enrichment, audio lessons, social replies, a broad marketplace, a fourth gamification agent, elaborate rewards, full experiment orchestration and multi-course analytics are outside the first frontend milestone. Keep encouragement lightweight and subordinate to learning evidence.

## 12. Reference files

- Primary brief: `proposal/[Group 72] LearnLoop Project Proposal_NeurIPS.pdf`.
- Editable final proposal: `proposal/[Group 72] LearnLoop Project Proposal_final.docx`.
- Supporting LaTeX: `proposal/source/LearnLoop_NeurIPS_2026_r8/` (retained together with its figures and style file).
- ThreadLearn references listed in Section 2 are read-only inspiration; no changes made there.

## 13. Three-agent activity interface (implemented 18 October 2026)

Add **Agent activity** to the main navigation, with contextual entry points from Materials and Learn. The screen shows three role cards, the current task and public tool name, a chronological event log, sources and output status. A separate runtime panel distinguishes proposed updates from accepted commits. It is a system control, not a fourth agent. Display task summaries and safe tool outcomes only; do not expose private reasoning, prompts, credentials or raw model responses.

| Workflow | Visible work | Completion boundary |
| --- | --- | --- |
| Prepare course | Expert retrieves evidence, proposes concepts and prerequisites; runtime validates | Publish accepted resources, or leave candidate resources unpublished for review |
| Choose activity | Tutoring loads learner evidence, checks eligibility, retrieves and assigns activity | Wait for the learner; Assessing does not run before a response |
| Assess and adapt | Assessing evaluates a submitted response and proposes evidence; runtime validates; handoff to Tutoring | Show committed evidence, adapt next activity, return to the learner |

These are separate workflow runs across a learning lifecycle. All three roles remain visible, including roles that are not required in the current run. A course-preparation completion must not imply an assessment has happened.

The local preview provides manually stepped scenarios for preparation, activity selection, assessment/handoff, resource review, retryable retrieval failure and checkpoint resumption. Every scenario is labeled scripted. Sample commits are isolated from the existing browser practice store and graph. Current MC grading still uses authored answer keys and local rules. Run creation, document processing and actual agent execution require the future backend.

The integration boundary is `AgentActivitySource`: fetch a validated run snapshot, subscribe after its sequence cursor, and submit an idempotent permitted retry/resume command. Zod schemas validate v1 snapshots, events and receipts. Duplicate event replay is harmless; missing sequences, wrong scopes, conflicting cursors and invalid commits stop the stream and require a snapshot refresh. Workflow record versions and learner evidence versions are distinct. A receipt acknowledges a command; only subsequent authoritative events change visible run state.

Implemented files: `frontend/src/lib/agent-activity/{contracts,reducer,demo-source,http-source}.ts`, `frontend/src/components/use-agent-run.ts`, `frontend/src/components/agent-activity.tsx`. Backend handoff details are in `frontend/docs/agent-backend-contract.md`. This activity adapter is ready for integration; the existing local practice and learner-state provider still needs its own backend adapter. No backend endpoints are implemented here.
