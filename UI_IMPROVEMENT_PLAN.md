# LearnLoop UI review and improvement plan

Reviewed 20 October 2026. Scope: every current application page, its shared navigation, and the learning/source interactions within those pages. This is an implementation plan; no application behavior was changed during the review.

## Review basis

- Inspected the running app at `http://127.0.0.1:3100`: Today, Learn (study and practice entry), My understanding, Materials, Progress, Agent activity, and Session summary.
- Reviewed the current Large Language Model course: 2 PDFs, 109 lessons/concepts, 218 prepared questions, 23 topics, and 25 activity runs. These are review-time observations, not permanent product totals.
- Visually inspected the default desktop browser viewport (approximately 900 × 760) and selected pages at 390 × 844. Phone inspection covered Learn, My understanding, Session summary, and shared navigation. Wider desktop layouts and all failure states still require implementation-time verification.
- Read the live route components, workspace provider, source viewer, graph, activity dashboard, API types, and relevant styles. Active routes use `LiveWorkspace`; older `views.tsx`, `learn-view.tsx`, `map-view.tsx`, and demo components are not the current product.
- Did not upload files, generate new content, submit answers, end sessions, or alter learner evidence. Assessment and recovery behavior below is based on source inspection where it was not exercised live.

The existing `FRONTEND_PLAN.md` contains useful product intent but still describes demo-era implementation and deferred integration. Use this document as the current UI improvement backlog; reconcile the old plan after implementation.

## Direction

Keep the warm off-white canvas, restrained green accent, clear cards, source-backed lessons, and three agent portraits. The main problem is hierarchy and continuity: the app exposes course data, but often leaves the learner to decide where to go, find their place, and interpret what changed.

**Simplification update:** the learner explicitly finds the interface too panel-heavy and switch-heavy. The simplification decisions below take precedence over earlier suggestions to add rails, tabs, summary cards, segmented controls, or section anchors. Preserve useful capabilities while reducing permanent UI. A reusable component does not need a visible border or card background.

## Simpler interface: revised layout decisions

### What is creating the clutter

The problem is the number of decisions presented before the content, as well as the number of bordered boxes. Simply making panels smaller would preserve the same cognitive load.

- **Map:** personal/course switch, three difficulty buttons, four clickable evidence counts, topic selector, related-links checkbox, material selector, evidence selector, and five zoom/reset controls. The evidence selector duplicates the clickable counts. Instructions and coverage sit in another large panel above the graph.
- **Learn:** study/practice switch, content totals, lesson selector, generation controls, source toolbar, practice entry, and previous/next controls. Learners must understand the app's modes before following a lesson.
- **Agent activity:** three large clickable agent cards, five status buttons, search, run selection, and another agent filter inside the timeline. These are valid capabilities, but they do not all need equal prominence.
- **Materials:** separate boxed areas for course creation, upload, library, and generation make an established course look like a setup form.
- **Shared shell:** breadcrumb, large page heading, course eyebrow, generic subtitle, Refresh, connection badge, footer, and sidebar encouragement repeatedly surround the actual task.

These findings combine the previous live visual inspection with a follow-up inspection of the current components. The following layouts are proposals, not implemented or usability-tested screens.

### Rules for the simpler version

1. **One main content surface per page.** Use headings, whitespace, and light dividers within it. Reserve a card for a separate task that needs a boundary, such as an active practice question.
2. **One primary action for the current step.** Change Submit to Next question when the step changes. Secondary links remain available without competing filled buttons.
3. **Actions replace unnecessary modes.** Practice this lesson enters practice; Back to lesson returns. Source links open sources. Neither needs a permanent switch.
4. **One control for each filter dimension.** Never keep both clickable status totals and a status dropdown. Show a filter count and active selections only after filtering.
5. **Keep essential controls visible.** Search, the current question's actions, errors, and task progress remain discoverable. Put occasional preferences and technical history behind a labeled control.
6. **Open context only when requested.** Sources, concept details, upload, and run details may use a drawer or dedicated detail view. Open one contextual drawer at a time and preserve the underlying place and focus.
7. **Avoid turning every paragraph into an accordion.** Lessons remain readable as continuous content. Disclosures are for optional detail, not mandatory steps.

### Page-by-page reduction

| Page | Default presentation | Remove or combine | Available on demand |
| --- | --- | --- | --- |
| Today | One Continue learning block, a short reason, and a compact recent-learning list | Separate goal, recommendation, review, quote, and statistics cards; competing upload action for an established course | Detailed progress through Progress; course setup through Materials |
| Learn | Lesson title, Choose lesson, continuous lesson, Practice this lesson | Permanent Study/Practice switch, totals beside modes, section toolbar, nested lesson cards | Searchable topic-grouped lesson picker; source viewer from citations |
| My understanding | Search, Filters, graph on desktop; topic list on phone | Large overview card, duplicate status filters, permanent personal/course and difficulty switch rows | Filter popover; view-as-list/map menu; selected-concept details |
| Materials | One document list with Add materials in the header | Always-visible Create course form and separate generation card | Upload dialog, course creation from course menu, document-specific preparation actions |
| Progress | One-line evidence summary and compact concept rows; recent practice below | Four boxed statistic cards, full concept prose, a new permanent Evidence/History tab bar | Search/filter options, concept detail, View all practice history |
| Agent activity | Chronological task list with current status and a single Filter action | Large agent filter cards, five permanent status buttons, second timeline agent filter | Agent/status filters; run details and technical trace |
| Session summary | One session recap with attempts and Continue action | Course-wide evidence panels and unrelated history | Individual answer analysis and source links |

### Learn: make study and practice one journey

Suggested default structure:

```text
Course name                                  Choose lesson
Lesson title
Learning objective

Short explanation with inline source links
Worked example
Key idea and common mistake
Quick recall

[Practice this lesson]
Previous lesson                               Next lesson
```

Choosing Practice this lesson replaces the reading area with the focused question and offers Back to lesson. The learner does not have to operate a mode switch first. Preserve the lesson position, selected question, and saved assessment while moving between them. General practice remains available through a secondary Practice across course link in the lesson picker.

Remove the outer lesson card where the page background and reading column already establish a clear surface. Use a subtle background or left rule for the worked example; do not separately box the takeaway, common mistake, recall, author, and action area. Keep agent identity to a small byline beside the relevant content.

Sources open from named citations in a drawer by default. A learner who regularly compares slides can choose Keep sources beside lesson on a sufficiently wide screen; avoid opening a second permanent column for everyone. Keep the lesson and question usable if sources fail.

### Map: put the graph before the controls

Suggested desktop structure:

```text
My understanding
[Search concepts________________] [Filters]
105 not assessed · 3 developing · 1 demonstrated · 0 review due

Graph                                         [+] [-] [Fit]

Select a concept to view its details.
```

- The numbers illustrate the reviewed course only. Derive them from current data and label the evidence level; make the level label open Filters rather than adding another switch row.
- Filters contains topic, material, evidence state, difficulty, and Show course structure. Use the current Intermediate default until the backend supports another target policy. Show chosen filters as removable chips after selection.
- Eliminate the separate related-links checkbox: show relevant related edges when a concept is selected, with their meaning in the legend. Keep a hide-related preference inside map options only if later use demonstrates a need.
- Retain Zoom in, Zoom out, and Fit near the canvas. Put Reset position and other occasional commands in map options instead of expanding the toolbar.
- Open concept details after an explicit selection. Start with its title, evidence state, and Open lesson; place prerequisites and relationships below. Keep the initial graph free of an automatically selected concept's large detail panel.
- Provide an explicit View as list/map menu action rather than another permanent segmented switch. Default phones to the topic list while retaining graph access.

### Shared navigation and chrome

- Keep five study destinations: Today, Learn, My understanding, Materials, Progress. Move Agent activity to a secondary desktop utility link and the course menu on phones; retain contextual View activity links for running or failed tasks. Preserve every existing route.
- Show the current course and page title once each. Remove the repeated My workspace breadcrumb, generic subtitle, decorative eyebrow, encouragement panel, and persistent marketing footer where they add no navigation value.
- Remove Refresh from normal page headers because the app already refreshes automatically. Offer Retry beside an actual failure and Reload data in the course/menu utilities.
- Show a small Saving/Saved indicator only beside an operation that needs reassurance. Surface connection issues when they affect the task; avoid a permanently boxed Connected badge.
- Keep a labeled course selector available on phones; simplifying navigation must not hide course switching or recovery actions.

### Avoid adding complexity while implementing the earlier plan

These decisions explicitly replace the earlier proposals for a permanent lesson rail, section-anchor toolbar, Study/Practice switch, Graph/List segmented control, four statistics cards, and Progress tabs. Searchable pickers, plain summaries, contextual actions, and detail views provide those capabilities with less permanent UI. The prior functional requirements, evidence safeguards, session scoping, and recovery acceptance criteria still apply.

Start with the shared shell and Learn simplification, then the map, then Materials/Progress/Activity. Introduce no new navigation destination as part of this pass. Defer combining My understanding and Progress into one route until learner testing demonstrates that the two purposes are confusing; that larger change is unnecessary to reduce the present clutter.

### How to verify the simplification

- Compare the same course, page, viewport, and task before and after. Record the number of bordered containers, permanent control groups, and visible competing actions; count closed drawers separately.
- Learn opens to the title and actual lesson content without a mode decision. A learner can enter practice, return to the same reading position, and open its source without losing work.
- The map shows usable graph/list content in the initial viewport at desktop and phone sizes; no filter dimension has two simultaneously visible controls.
- Materials opens to the existing library; course creation and upload appear only when invoked or needed for onboarding.
- Each page has one clearly dominant action when an action is needed. Selected filters remain visible and clearable; required errors and pending saves are never hidden in a menu.
- Validate the core tasks with a learner: resume a lesson, find another topic, consult a source, answer a question, inspect evidence, and recover a failed task. Fewer panels alone is insufficient if discovery or completion becomes harder.

## Simplified layout wireframes

These drawings show proposed structure, not implemented screens. Outer rectangles represent the browser or an opened dialog; they are not instructions to put every section inside a card. Inside each page, default to an unboxed content column with whitespace and light dividers. `[Action]` denotes a primary button; `Link →` denotes a secondary action; `v` denotes a menu or picker. Content and counts are illustrative, not new claims about learner progress.

### Shared desktop shell

```text
+-------------------+----------------------------------------------------+
| learnloop.        | Large Language Model v                             |
|                   |                                                    |
| Today             | PAGE TITLE                      Page action, if any |
| Learn             |                                                    |
| My understanding  |                                                    |
| Materials         |          One main content area                     |
| Progress          |                                                    |
|                   |          Reading, graph, or list                   |
|                   |                                                    |
|                   |                                                    |
|                   |                                                    |
| Agent activity    |                                                    |
+-------------------+----------------------------------------------------+
```

The course picker appears once, at the top of the workspace. Agent activity remains a secondary utility. No separate breadcrumb bar, permanent connectivity badge, encouragement card, or marketing footer. Page-specific drawings below show only the main content area inside this shell.

### 1. Today

Implemented 20 October 2026: the live Today page now uses an unboxed learning action and up to three recently practiced concepts with saved difficulty-specific evidence. The main action opens the most recently practiced available lesson, falling back to the first ready lesson. It does not claim to resume an unanswered question. Course setup, preparation, loading, and history-error states are handled. Shared navigation remains a separate follow-up. Verified desktop/390px phone layout, lesson navigation, typecheck, lint, 29 existing tests, and production build. Preview: [Today page](frontend/docs/today-simplified-preview.png).

```text
+-----------------------------------------------------------------------+
| Today                                                                 |
|                                                                       |
| Continue learning                                                     |
| Inference service economics                                           |
| Pick up your lesson where you left off.                                |
|                                                                       |
| [Resume lesson]                                                       |
|                                                                       |
| Recent learning                                                       |
| --------------------------------------------------------------------- |
| FP16 and BF16                 Demonstrated             Open lesson ->  |
| Quantization                 Developing               Open lesson ->  |
|                                                                       |
| View all progress ->                                                  |
+-----------------------------------------------------------------------+
```

One dominant next action. When an unanswered question is the saved context, use Resume question instead. No separate goal, statistics, review, recommendation, or quote panels. Show onboarding here only when there is no usable course content.

### 2. Learn: lesson

Implemented 20 October 2026: continuous reading layout; searchable lesson picker grouped by published topic; on-demand source dialog with phone sheet layout; Practice this lesson and Back to lesson in place of the permanent mode switch. Previous/Next and picker selections update the concept URL; lesson/practice views support browser history. Lesson and practice components stay mounted when switching to preserve in-page reading/question state; this does not add durable answer-draft storage across reloads. Material generation controls remain in Materials. Practice now shows difficulty and opens sources on demand. Verified lesson search and no-results, source preview and keyboard focus restoration, selected-lesson reload, general-practice entry/return, desktop and 390px phone layout, typecheck, lint, all 29 existing tests, and production build. Live verification did not generate questions or submit assessments. Previews: [Desktop](frontend/docs/learn-simplified-preview.png), [Phone](frontend/docs/learn-simplified-mobile.png).

```text
+-----------------------------------------------------------------------+
| Learn                                                Choose lesson v  |
|                                                                       |
| Inference service economics                                           |
| Understand how cost, capacity, and response times connect.             |
| Expert                                                                |
|                                                                       |
| A short explanation with a named source link [Lecture 2, p. 8].        |
|   - The first key point                                               |
|   - The next key point                                                |
|                                                                       |
| Worked example                                                        |
|   1. Given values                                                     |
|   2. Formula and calculation                                          |
|   3. Result and interpretation                                        |
|                                                                       |
| The key idea                                                          |
| A concise takeaway.                                                   |
|                                                                       |
| A common mistake                                                      |
| A short explanation.                                                  |
|                                                                       |
| Quick recall                                                          |
| > What determines rental cost?                                        |
|                                                                       |
| [Practice this lesson]                                                |
|                                                                       |
| <- Previous lesson                                   Next lesson ->   |
+-----------------------------------------------------------------------+
```

This is one continuous reading surface. Worked example may have a subtle left rule; the remaining headings do not need card backgrounds. The lesson picker contains search and topic groups. Sources open from citations; neither needs an always-visible side panel.

### 2a. Learn: question and feedback

```text
+-----------------------------------------------------------------------+
| <- Back to lesson                                          Session v  |
|                                                                       |
| Inference service economics                         Intermediate      |
| Tutor                                                                 |
|                                                                       |
| Which change reduces the monthly rental cost under these conditions?  |
|                                                                       |
| ( ) Answer A                                                          |
| ( ) Answer B                                                          |
| ( ) Answer C                                                          |
| ( ) Answer D                                                          |
|                                                                       |
| [Submit answer]      Get a hint                   Lecture 2, p. 8 ->   |
|                                                                       |
| After assessment, in this same content area:                          |
| --------------------------------------------------------------------- |
| Correct / Keep learning / Needs another check                          |
| Reviewer                                                              |
| Explanation and confirmed evidence outcome.                           |
|                                                                       |
| [Next question]                                                       |
+-----------------------------------------------------------------------+
```

The drawing shows the before/after states together for explanation; Submit and Next question are not competing primary buttons. Keep the answered options visible with feedback. Session menu contains End session. A pending or failed save is shown directly beside the answer actions, never hidden in that menu.

### 3. My understanding

Empty search update (20 October 2026): when a map search or filter has no matches, the atlas remains mounted at its current size and position, with a compact empty-state message and a Clear search and filters action over the canvas. The changing results summary row is omitted while there are zero matches, avoiding the extra vertical shift above the map. The phone list keeps its own empty state. Verified the live map remains mounted at the same document top and height before and after a zero-result search; lint, typecheck, and production build pass.

Pan and zoom update (20 October 2026): scrolling the atlas now zooms in or out around the pointer, including trackpad pinch/shift-scroll input. Zoom interpolation runs through animation frames and updates the canvas transforms directly; the 109 concept buttons do not re-render for every wheel step. Drag panning is also frame-batched. Plus/minus controls zoom around the viewport center. The hint and region label now explain wheel zoom and drag panning. Verified lint, typecheck, and production build. Browser controls and live map render correctly. The browser surface used here does not expose a physical wheel-input action, so wheel zoom itself has not been manually exercised with a mouse/trackpad.

Concept study modal update (20 October 2026): full concept details now use Goals, Learning material, and Quizzes tabs, so reading and practice stay on the map. Goals shows the prepared objective, concept context, evidence, and prerequisite readiness. Learning material reuses Learn's lesson renderer, including equations, worked examples, takeaways, common mistakes, recall cards, and original source slides. Quizzes reuses the live practice component with an explicit concept target, hints, submission, reviewer feedback, and next-question controls. Tabs remain mounted so a pending answer and each panel's scroll position survive tab changes; closing the modal does not add durable unsaved-answer storage. The title, Close button, and keyboard-accessible tabs remain fixed above the scrolling panel. If the shared session changes topic elsewhere, the modal hides unrelated quiz content and offers Resume this concept. Verified desktop and 390px layouts, keyboard arrow navigation, live concept question loading, checked-answer retention across tabs, shared-session mismatch handling, lint, typecheck, all 40 tests, and production build. No assessment was submitted during live verification. Previews: [Goals](frontend/docs/understanding-study-goals.png), [Learning material](frontend/docs/understanding-study-material.png), [Phone](frontend/docs/understanding-study-mobile.png).

```text
  Concept title                                         Close ×
  [Goals]   [Learning material]   [Quizzes]
  -------------------------------------------------------------
  Goals: objective, context, prerequisites
  Learning material: lesson, worked example, sources
  Quizzes: question → submit → feedback → next question
  (Only the selected tab's content is shown; the map stays behind.)
```

Atlas and preview update (20 October 2026): topic containers now look like soft map regions on a dotted canvas, with faint paths for published connections between topics. A compact fixed-size navigation stack offers zoom and Fit; All topics gives a whole-course overview. Hover or keyboard focus opens a small topic preview with the concept title, parent topic, and evidence. A mouse click opens the full details modal. On touch, the first tap pins the preview; View details or a second tap opens the modal. Escape, outside interaction, panning, and zoom dismiss the preview. Preview placement flips and clamps inside the map on narrow screens. Full details retain lesson, readiness, and source information. Phones retain the default topic list with a map option. Verified compact preview, details entry, Escape/focus behavior, 390px layout, map-edge placement checks, lint, typecheck, all 40 tests, and production build. Touch-specific pointer handling is implemented; browser verification used mouse/keyboard at phone dimensions. Previews: [Atlas](frontend/docs/understanding-atlas-preview.png), [Phone preview](frontend/docs/understanding-atlas-mobile-preview.png). This supersedes direct full-modal opening on the first touch tap.

```text
  Course atlas                                      All topics
  · · · · · · · · · · · · · · · · · · · · · · · · · · · ·
       ( Inference serving )           ( Scheduling )
       (   o   o   o       ) - - - - - (  o  o  o   )
       (     o   o         )           (            )
             |                                      [+]
             +-- Concept preview                    [−]
                 Inference Service Economics        [Fit]
                 Developing · intermediate
                 View details →  [full modal]
  Evidence color key
```

Grouped-bubble update (20 October 2026): the map now renders the 23 published topic groups as large circular containers, holding all 109 concepts as small, unlabeled evidence-colored bubbles. Only container titles appear on the map; concept names remain available to assistive technology and in the click/keyboard popup. Popups show the selected concept title, parent topic, evidence, and lesson link. Small bubbles have equal size; container sizes accommodate their contents and reserve a clear title area. Published cross-topic links guide container spacing; unassigned concepts remain in an explicit fallback group. No generated grouping or backend write was needed for the existing course. Layout checks cover non-overlapping containers, contained and non-overlapping concepts, title-area clearance, stable positions, and unique membership. Verified the live 23/109 group/concept counts, empty small-bubble text, popup click/Escape/focus behavior, search, phone list and map popup, typecheck, lint, all 38 tests, and production build. Latest previews: [Grouped map](frontend/docs/understanding-grouped-preview.png), [Popup](frontend/docs/understanding-grouped-popup.png), [Phone popup](frontend/docs/understanding-grouped-mobile-popup.png). This supersedes the flat bubble presentation described below.

Bubble-map update (20 October 2026): the rectangular, layered graph has been replaced with equal-size circular concepts in a deterministic relationship layout. Published prerequisite/related links provide stronger attraction; topic membership supplies weaker grouping. Spacing is approximate and is not a numerical semantic-similarity score. Evidence changes color without moving or resizing concepts. Only the selected bubble's prerequisite arrows and related links are drawn; full titles remain available through accessible names, hover titles, and details. Shorter saved lesson titles are used inside bubbles where available and are searchable. Layout computation is reused across unchanged polling snapshots. Existing filters, source/lesson links, pan/zoom, and neutral course structure are retained. Phones still default to the topic list in its published teaching order, with bubbles available through Options. Verified 109 equal-size, non-overlapping live bubbles, stable positions across evidence-mode changes, selected-arrow rendering, visible-title search, mobile overflow/default/explicit-map behavior, typecheck, lint, 37 tests, and production build. No backend data or learner evidence was changed. Latest previews: [Bubble map](frontend/docs/understanding-bubbles-preview.png), [Phone list](frontend/docs/understanding-bubbles-mobile.png). This supersedes the rectangular graph depicted below.

Implemented 20 October 2026: removed the overview card, permanent view/difficulty switch rows, duplicate evidence filters, related-link checkbox, and always-open details panel. The page now presents Search, one Filters action, plain evidence counts, and the graph; phones default to a topic-grouped list. Options contains map/list choice, reset/whole-map fit, and organization details. Selecting a concept opens a dialog/sheet; closing it retains the graph highlight and selected-concept related links. Course structure is neutral in both graph and details. Search, filters, difficulty, view preference, and concept selection are URL-backed; a plain `/map` has no automatic concept selection. Verified filtering/clearing, empty search, source/lesson entry points, selected concept/list reload, neutral details, desktop/390px phone layouts, typecheck, lint, 32 tests including three new URL-state checks, and production build. No learning evidence or course organization was changed. Previews: [Desktop](frontend/docs/understanding-simplified-preview.png), [Phone](frontend/docs/understanding-simplified-mobile.png).

```text
+-----------------------------------------------------------------------+
| My understanding                                           Options v  |
|                                                                       |
| Search concepts...                                      Filters       |
| Intermediate: 105 not assessed / 3 developing / 1 demonstrated         |
|                                                                       |
|                         Inference serving                             |
|                               |                                       |
|                  +------------+------------+                          |
|                  v                         v                          |
|             GPU costs                  Throughput                     |
|                  |                                                    |
|                  v                                                    |
|             Fleet planning                                            |
|                                                                       |
|                                                [ - ] [ + ] [Fit]      |
| Solid arrows: prerequisites. Dashed links: related ideas.              |
+-----------------------------------------------------------------------+
```

Graph labels above are illustrative. Filters opens topic, material, state, difficulty, and course-structure settings in one place. Options offers View as list and occasional map commands. Counts are text, not a second filter toolbar. Selecting a concept opens its details on demand; no details panel is open initially.

### 4. Materials

```text
+-----------------------------------------------------------------------+
| Materials                                            [Add materials]  |
|                                                                       |
| Lecture 2                                                             |
| COMP7608B_Lecture_2_v1 (1).pdf                                          |
| Ready for learning / 63 pages / 51 lessons                             |
| Open lessons ->                             Preview       Details v   |
| --------------------------------------------------------------------- |
| Lecture 5                                                             |
| COMP7608B_Lec05.pdf                                                    |
| Ready for learning / 72 pages / 58 lessons                             |
| Open lessons ->                             Preview       Details v   |
|                                                                       |
+-----------------------------------------------------------------------+
```

Use rows separated by light dividers. Upload appears in a dialog; Create course lives in the course menu. A processing document shows its actual stage and View activity in its own row. Coverage and supported regeneration actions live in Details, not an additional course-wide panel.

### 5. Progress

```text
+-----------------------------------------------------------------------+
| Progress                                                              |
|                                                                       |
| Intermediate: 1 demonstrated / 3 developing / 105 not assessed          |
|                                                                       |
| Search concepts...                                      Filters       |
|                                                                       |
| Concept                          Basic       Intermediate   Advanced   |
| --------------------------------------------------------------------- |
| Inference service economics      Not assessed Developing    Not assessed|
| FP16 and BF16                    Not assessed Demonstrated  Not assessed|
| Quantization                    Not assessed Developing    Not assessed|
|                                                                       |
| Load more                                                             |
|                                                                       |
| Recent practice                                                       |
| --------------------------------------------------------------------- |
| Quantization              Correct / Intermediate       View answer -> |
| Inference economics       Hinted / Intermediate        View answer -> |
|                                                                       |
| View all practice history ->                                          |
+-----------------------------------------------------------------------+
```

Concept names open detail; full descriptions are absent from the initial list. The table and recent history are plain sections on the same surface, without a tab switch or statistic-card row. On phones, render each concept as a compact row with the current level's state; show the other levels in its detail view.

### 6. Agent activity

```text
+-----------------------------------------------------------------------+
| Agent activity                                             Filter     |
|                                                                       |
| Current work                                                          |
| Preparing Lecture 5          Expert / In progress      View details -> |
|                                                                       |
| Earlier activity                                                      |
| --------------------------------------------------------------------- |
| Answer reviewed              Reviewer / Complete      View details -> |
| Practice question ready      Tutor / Waiting           Resume ->       |
| Lecture 2 prepared           Expert / Complete         View details -> |
|                                                                       |
| Load more                                                             |
+-----------------------------------------------------------------------+
```

Illustrative states only: actual actionability comes from current backend records. No active work means the Current work heading disappears. Filter contains agent, status, and search. A selected run opens a detail view with Back to activity, outcome, permitted actions, then optional Timeline and Technical details. Three large agent cards and the second agent filter are removed.

### 7. Session summary

```text
+-----------------------------------------------------------------------+
| Session summary                                                       |
| Inference service economics                                           |
|                                                                       |
| 2 answers submitted / 1 independent / 1 hinted                         |
| Confirmed evidence change, if recorded for this session.               |
|                                                                       |
| Your answers                                                          |
| --------------------------------------------------------------------- |
| Question 1          Correct / Independent               View answer -> |
| Question 2          Incorrect / Hinted                  View answer -> |
|                                                                       |
| Next step                                                             |
| Review the worked example before another independent check.           |
|                                                                       |
| [Review lesson]                                                       |
| Back to Today ->                                                      |
+-----------------------------------------------------------------------+
```

One recap, one attempt list, one next action. Counts, evidence changes, and next step require actual session data. No course-wide concept panels; missing historical attribution is explicitly unavailable.

### On-demand context: one drawer or dialog at a time

```text
+-----------------------------------------+-----------------------------+
| Existing lesson or map                  | Source / Concept details    |
|                                         |                    Close X  |
| Reading position and answer preserved.  |                             |
|                                         | Title                       |
|                                         | Requested content           |
|                                         |                             |
|                                         | Relevant action, if needed  |
+-----------------------------------------+-----------------------------+
```

Source drawer: document, page navigation, preview, compact zoom menu, extracted-text link. Concept drawer: title, selected-level state, Open lesson, then prerequisites and evidence. Filters: a compact popover on desktop, a sheet on phones. Upload: dialog with destination and per-file queue. These are alternatives triggered by specific actions, not panels mounted side by side. Drawers need a clear title/close action, keyboard focus management, and return to the originating control.

### Phone layout: lesson and topic list

```text
+-------------------------------+   +-------------------------------+
| Large Language Model v        |   | Large Language Model v        |
|                               |   |                               |
| Learn          Choose lesson  |   | My understanding    Options v |
|                               |   |                               |
| Inference service economics   |   | Search concepts...    Filters |
| Learning objective            |   | Intermediate: 1 demonstrated  |
|                               |   |                               |
| Short explanation             |   | Inference serving             |
| Source: Lecture 2, p. 8 ->     |   | ----------------------------- |
|                               |   | Inference economics           |
| Worked example                |   | Developing                 >  |
| 1. Given values               |   |                               |
| 2. Calculation                |   | Fleet planning                |
| 3. Interpretation             |   | Not assessed               >  |
|                               |   |                               |
| Key idea                      |   | Precision and quantization    |
| Quick recall                  |   | ----------------------------- |
|                               |   | FP16 and BF16                 |
| [Practice this lesson]        |   | Demonstrated               >  |
|                               |   |                               |
| Today Learn Map Materials     |   | Today Learn Map Materials     |
|             Progress          |   |             Progress          |
+-------------------------------+   +-------------------------------+
```

The two-line navigation drawing is schematic, not a prescribed wrap: use five equal destinations with icons and short labels in one fixed bottom bar. Use Map as the compact navigation label for My understanding on phones. Reserve bottom safe-area space so content is not covered. The phone topic list opens concept details on selection; Options offers View as map. Source/detail drawers become full-height sheets with an explicit Back/Close action. Longer content scrolls naturally; nothing is shrunk to force it into one screen.

## Page purposes and priorities

Design every page around one question:

| Page | Question it should answer | Primary action |
| --- | --- | --- |
| Today `/` | What should I do next, and why? | Resume, or open an eligible recommended lesson |
| Learn `/learn` | What am I learning, and how do I check it? | Study the selected lesson or answer the current question |
| My understanding `/map` | How do these ideas connect, and where do I need evidence? | Inspect a concept and open its lesson |
| Materials `/materials` | What have I added, and is it ready? | Add material to the selected course |
| Progress `/progress` | What does my saved practice show? | Review a concept or assessment |
| Agent activity `/agents` | What is happening, and does anything need me? | Inspect an active/actionable run |
| Session summary `/learn/summary` | What happened in this session, and what comes next? | Continue with a supported next step |

Priorities: **P0** = misleading state or broken journey; **P1** = core usability and scaling; **P2** = refinement after the journey works.

## Shared shell and design system — P0/P1

### Findings

- The header always says “Connected workspace,” regardless of loading or request failure. The footer similarly makes an unconditional server-save statement.
- The same generic description and Refresh action repeat across several pages, occupying valuable space without clarifying the next action.
- On phones, the course picker disappears and all six destinations share a narrow bottom bar. Long labels wrap; the development indicator also overlaps navigation in the reviewed dev build.
- Supporting text and operational controls frequently use 9–12px type. The calm palette is worth retaining, but small muted labels need a readability pass.
- The workspace polls all four course resources together every four seconds. One failed request prevents the batch from updating; resource-specific loading and stale states are not represented.

### Plan

1. Create a compact page header: course context, page title, page-specific supporting text, and the page's actual primary action. Move manual refresh into a quiet reload control with an accessible name.
2. Derive connection presentation from requests: Connecting, Updated just now, Reconnecting, or Unavailable. Distinguish connection health from whether an answer has been saved.
3. Keep visible stale data during recoverable failures and label it with the last successful update. Give each failed resource an appropriate retry without replacing the entire page.
4. Add a phone header course switcher. Use five main bottom destinations; put Agent activity in an explicit More/menu entry and keep contextual activity links beside work in progress. Keep all six desktop destinations.
5. Give phone navigation safe-area padding and reserve matching page-bottom space. Verify the deployed interface without development overlays.
6. Standardize typography: approximately 16px reading text, 14px supporting text, 12px minimum for nonessential metadata, and 28–32px page titles. Set a comfortable lesson reading measure around 65–75 characters.
7. Establish reusable page headers, cards, action groups, empty states, status badges, filter bars, skeletons, error notices, and detail panels. Pair status color with text or an icon.
8. Use 44px touch targets, visible focus, semantic labels, and reduced-motion-aware scrolling. Keep horizontal scrolling inside equations, tables, source canvases, and graph panels.

**Acceptance:** course switching is available at 390px; navigation does not cover content; connectivity never claims success after an initial failure; keyboard focus remains visible; 200% text zoom preserves usable controls. Do not remove existing skip navigation or focus styles.

## Today — P1

### Findings

The current page is one large generic hero with material/concept totals and Start learning / Upload materials. Existing practice evidence and recent activity do not affect that presentation. Most of the viewport is unused, and Start learning simply opens Learn's default study view.

### Plan

- Replace the generic hero with **Continue learning**: selected concept, current mode, saved-question status where available, and a specific Resume action.
- When there is no active session, offer one eligible lesson with a short, evidence-based reason. If no recommendation contract exists, label a deterministic starting lesson “Start here”; do not imply that it was adaptively selected.
- Add a small course snapshot at an explicitly selected difficulty: Not assessed, Developing, Demonstrated, Review due. Counts describe evidence, not time spent or a mastery percentage.
- Show at most three relevant next items: review due, recent assessed concept, or material still preparing. Hide empty sections and retain one clear primary action.
- Make onboarding contextual: no course → Create course; no documents → Upload; processing → preparation status; partial readiness → Open ready lessons; ready course → Resume/Start.
- Demote Upload materials after onboarding; it remains available through Materials.

**Acceptance:** a returning learner can identify the concept and action immediately; Resume opens the actual saved context; zero-review and preparing states do not show invented tasks or estimates.

## Learn: study lessons — P1

### Findings

- A 109-option dropdown is the main lesson navigator. It does not expose the existing 23-topic structure or offer search.
- Selection starts with the first lesson unless the incoming URL supplies a concept. Dropdown and Previous/Next changes do not write the selected concept back to the URL.
- Long worked examples push quick recall, practice, and source material far down the page when the source column stacks below the lesson at widths under 1100px.
- The source panel's explanatory copy refers to a question even in study mode.

### Plan

1. Add a searchable topic/lesson navigator using published topics and material filters. On desktop it can be a collapsible rail; on phones use a labeled Lesson contents sheet.
2. Keep a compact lesson header with topic, title, objective, source links, and practice entry. Preserve the existing short explanations, math, worked steps, takeaways, common mistakes, and hidden flashcard backs.
3. Use section anchors for Overview, Worked example, Key idea, Recall. Keep examples expanded initially; let learners collapse a long example without hiding the core explanation.
4. Add an Open sources action beside the lesson title. On narrow layouts open a source sheet/panel with a return-to-lesson action instead of requiring a scroll through the entire lesson.
5. Persist course, concept, and study/practice mode in URL state. Preserve navigation context on reload and browser back/forward. Distinguish a last-viewed lesson from an assessed concept state.
6. Keep Previous/Next within an explicit published sequence and identify the next title. Reading navigation must never imply demonstrated understanding.
7. Replace technical question-bank emphasis with Study / Practice labels and useful availability copy. Retain counts as secondary metadata.

**Acceptance:** find any lesson by title or topic without scrolling 109 options; reload retains the selected lesson and mode; sources open without losing the reading place; equations stay inside their own scroll region at 390px.

## Learn: practice — P0/P1

### Findings

- Practice already retains the assessed question and selected answer until Next question, and uses backend grading and idempotent submission. Preserve those safeguards.
- Difficulty exists in the activity type but is not visibly presented in the practice card.
- End session clears the local session state and stays on Learn; it does not enter Session summary.
- Starting/resuming is required before the current session is discovered in this component. Navigation continuity should be explicit.

### Plan

- Present concept, difficulty, focused/general practice mode, and source action above the prompt. Offer a concise selection reason only when supported by public backend data.
- Separate answer states clearly: unanswered → saving answer → checking answer → feedback ready → next question. Distinguish saved response, pending assessment, and committed evidence.
- Keep Submit as the primary pre-assessment action and Next question as the primary post-assessment action. End session is secondary and visually separated.
- Explain hint use beside the hint action: it is recorded for this attempt. Preserve hint visibility and selected answer through supported resume flows.
- Feedback should show outcome, why the answer works, assisted/independent status, and any confirmed evidence change. Avoid inferring demonstrated status from correctness alone.
- Convert prerequisite and session-conflict messages into clear recovery cards with a named lesson/prerequisite action. Retain backend enforcement.
- Route a successful End session to a summary for that session. Show an inline retry if ending fails, preserving the current question and analysis.

**Acceptance:** repeated Submit cannot create duplicate evidence; failure/retry retains the selected option; an assessed question stays visible until Next; focused practice stays on its concept; ending reaches the correct session summary.

## Shared source viewer — P1

- Retain cited page bubbles, synchronized page arrows, Fit/150%/200% controls, extracted text, and retry behavior.
- Make the heading/copy context-aware: “Source for this lesson” versus “Source for this question.” Keep uncited material browsing explicitly labeled.
- Show document title, cited page, and current page distinctly when the learner browses away from a citation; provide Return to cited page.
- Provide source sheets at phone/tablet widths, with keyboard focus containment and restoration; retain a side-by-side layout where reading and slides both fit comfortably.
- Improve page input editing so users can replace a page number naturally before validation; support Enter/Go, bounds messages, and disabled end arrows.
- Distinguish empty extracted text from text still loading. Source image/text failures must leave the lesson and answer usable.

**Acceptance:** source opening, zooming, and retry never reset an answer or lesson; a failed image still offers extracted text; multiple-document citations remain distinguishable.

## My understanding — P1

### Findings

- The graph already supports topics, search, evidence levels, filters, related edges, pan/zoom, and an accessible list. Preserve this investment.
- At the reviewed desktop and phone sizes, overview text and controls consume the first screen before any graph is visible.
- The concept list is hidden under an accessibility disclosure although it is a useful browsing mode for everyone.
- The Course structure mode removes personal graph colors, but `KnowledgeDetails` still renders learner status and readiness. That makes the mode boundary inconsistent.
- Selection uses URL replacement; filters and zoom are local. Back/forward cannot fully reproduce a browsing sequence.

### Plan

1. Compress the overview into a single toolbar: Understanding / Course structure, difficulty where applicable, and counts. Move organization coverage and graph instructions into an About this map disclosure.
2. Give the graph and a topic/list browser first-class Graph / List views. Default phones to a readable topic list with an obvious graph switch; retain the equivalent semantic list on all devices.
3. Group secondary filters behind Filters on phones; show active filter chips and Clear filters. Keep search directly available.
4. Add Fit topic and Center selected alongside full-map Fit. With 109 concepts, fitting everything can make labels unreadable; preserve the topic context.
5. Desktop: graph with adjacent concept details where space permits. Phone: concise selected-concept card or sheet with Open lesson, readiness, then optional relationships/evidence.
6. Keep prerequisite arrows and related lines distinct. Explain unmet prerequisite names and link to their lessons. Never gate reading because practice is blocked.
7. Make Course structure consistently neutral, including its detail panel. Personal evidence/history belongs in Understanding mode.
8. Preserve meaningful selection changes with navigation history; persist view, difficulty, topic and filters. Handle invalid concepts and no-match filters explicitly.

**Acceptance:** graph/list browsing begins near the top of the page; all concepts can be reached by keyboard; changing displayed difficulty does not change practice eligibility; Course structure exposes no personal evidence; deep links reopen the intended selection.

## Materials — P1

**Implemented in the current simplification pass:** the selected course now opens on its saved-material list, with the current course and file count in a compact toolbar. Course creation and upload are opened only when requested, in dialogs that keep the destination course visible. Each file row shows its own readiness, pages, lesson/quiz counts, and source action; optional coverage detail stays collapsed. Empty courses retain a clear next action, and existing preparation/review status remains available below the library. Desktop and 390px phone layouts were checked; the phone layout has no horizontal page overflow. See [desktop preview](frontend/docs/materials-simplified.png) and [phone preview](frontend/docs/materials-simplified-mobile.png).

### Findings

Create a course and a large upload form precede the existing library even when a populated course is selected. Saved materials are pushed below the initial viewport. Processing status is mostly prose; needs-review material has no supported manual approval path.

### Plan

- Make the selected course's library the main content. Put Add materials in the page header and move Create course into the course switcher/menu, opening an accessible dialog.
- For an empty course, keep the upload area prominent. For an existing library, use a compact upload area or dialog that shows the destination course clearly.
- Show a per-file queue: filename, size, local validation, uploading, saved, processing, ready, or failed. A saved upload receipt must not look like completed preparation.
- Put readiness, pages, lesson availability, and primary actions on each document row/card. Add Open lessons, Explore concepts, and Preview where data supports them.
- Keep detailed passage/section coverage and regeneration options in a document details area. Replace formatting-version language with a plain explanation of what the action improves.
- Treat duplicates as a clear “Already in this course” outcome; allow retrying failed files without resending successful ones. Prevalidate all selected files before uploading.
- For review-required material, explain why it cannot be used and provide View activity. Do not add an approval button without backend support.

**Acceptance:** existing material is visible before course-creation controls; each file has its own result; partial batch failure preserves successful uploads; ready and still-processing resources are clearly different; no unsupported action appears.

## Progress — P1

**Implemented in the current simplification pass:** Progress now leads with a compact count table for demonstrated, developing, review-due, and not-assessed concepts at each difficulty. It shows five recent answers with feedback behind expandable rows; the full answer history and concept browser expand only when requested. Concept search filters titles and summaries, while descriptions, prerequisites, and source notes open on demand. Removed the permanent Refresh action from this page. Desktop and 390px phone layouts were checked; the phone page has no horizontal overflow. See [desktop preview](frontend/docs/progress-simplified.png) and [phone preview](frontend/docs/progress-simplified-mobile.png).

### Findings

Progress renders 109 full concept descriptions with three plain evidence pills each, followed by the entire assessment history. It lacks an overview, search, filters, and direct concept-specific actions. Feedback and explanation can repeat substantial text.

### Plan

1. Start with difficulty-specific state counts and a small Needs attention / Recently practiced section. Reuse the same state labels and counts as the map.
2. Replace the full prose list with a searchable, filterable evidence table: Concept, Basic, Intermediate, Advanced, and Open details. Group by topic/material and paginate or progressively load rows. On phones use compact cards.
3. Put descriptions, prerequisites, source notes, and longer explanations in the concept detail view. Link directly to its lesson and filtered assessment history.
4. Make History a separate tab/section reachable at the top. Add concept, difficulty, outcome, hint-use, and date filters with clear empty states.
5. Use concise attempt rows with expandable feedback, displaying the chosen answer and question only when the backend actually retains/exposes them. Do not reconstruct missing records.
6. Display uncertainty and assisted evidence explicitly. Use counts or trend charts only when their meaning and underlying data are supported; do not equate activity count with understanding.

**Acceptance:** a learner can find a particular concept or latest answer without traversing 109 descriptions; map and progress agree at the same difficulty; history filters survive a reload; no fabricated attempt detail or trend appears.

## Agent activity — P1/P2

**Implemented in the current simplification pass:** replaced the three large role cards and five status buttons with a compact run-count line and one filter disclosure. The feed shows eight recent activities at first, with search, agent, and status filters and URL-backed selection available on demand. Selecting a run opens a focused full-page detail with a Back to activity action; stage notes, timeline, outputs, and validation remain available as collapsed disclosures. Returning preserves the selected filters and list position. Desktop and 390px phone list/detail views were checked without horizontal overflow. See [desktop preview](frontend/docs/agent-activity-simplified.png) and [phone preview](frontend/docs/agent-activity-simplified-mobile.png).

### Findings

This is one of the more developed pages: agent identities, status filters, search, run selection, grouped events, outputs, and validation are already present. The team cards take substantial vertical space. Historical waiting/attention states can resemble current learner tasks. Selected runs are read from the URL initially but run clicks do not update it.

### Plan

- Put active/actionable work first with a short summary and explicit Resume practice / View material / Retry action where supported. Keep completed history available.
- Condense team cards after the learner knows the roles; keep portraits and role filters. Avoid a second large introductory heading ahead of the work list.
- Separate historical run status from current actionability using authoritative session/material state. Do not relabel backend history; explain resolved or superseded issues only when supported.
- In run details, show outcome and next action first, then an expandable timeline, outputs/sources, and validation details.
- Persist selected run and filters in the URL. Use human concept titles for saved changes and make supported outputs/sources navigable.
- On phones, use a list-to-detail view with Back to activity rather than an extended page containing every run followed by its details. Preserve list position.
- Retain advertised retry/resume commands, idempotency, and validation boundaries. Expand “Updates every 4 seconds” into last-update/reconnection feedback only when useful.

**Acceptance:** a contextual activity link opens the intended run; switching runs produces shareable/reloadable context; completed historical work is not presented as a fresh blocker; only advertised commands are offered.

## Session summary — P0

### Findings

The route currently renders the course-wide `AssessmentHistory` and `Concepts` components. It has no session scope, no before/after attribution, and no direct transition from End session. This is the largest mismatch between a page's name and behavior.

### Plan

1. Give the route an explicit course/session identity and load the completed session's records. Never silently fall back to all course history if the session is missing.
2. Show session outcome: concepts practiced, submitted answers, independent versus hinted attempts, pending assessments, and confirmed evidence changes attributable to this session.
3. Show a concise attempt list with difficulty and outcome; allow feedback expansion and a return to source/lesson.
4. Recommend one supported next action: review the same lesson, complete a prerequisite, continue independent practice, or open the next eligible concept. Preserve focused practice intent.
5. Handle no attempts, pending assessment, already-ended session, missing/invalid session, and unavailable summary data explicitly.
6. If historical before/after evidence was never captured, say it is unavailable. Add future snapshot/commit attribution rather than comparing current course state and claiming a session delta.

**Acceptance:** only the named session's attempts appear; an empty session never inherits old attempts; reload reproduces the summary; late assessments update their own rows; no evidence delta is guessed.

## Data and implementation boundaries

| Capability | Current frontend support | Work to confirm before implementation |
| --- | --- | --- |
| Topic/lesson search, filtering, shared badges | Existing course/topics/materials/evidence data | Primarily frontend work; reuse current records |
| Readiness and difficulty display | Activity difficulty; current UI assumes Intermediate prerequisites | Match the backend policy; do not invent per-concept target difficulties |
| Durable resume and Today recommendation | Start/resume API and session type exist; current component keeps session in local React state | Inspect backend discovery/checkpoint endpoints and expose authoritative active context if missing |
| Session summary | Current course-level history type lacks session identity | Confirm backend session query, attempt linkage, and committed-change attribution; extend contracts as needed |
| Detailed evidence and review timing | Learner type exposes state and optional reviewAt | Use available fields; qualifying counts and historical deltas require explicit contracts |
| Per-file upload progress | Sequential upload receipts and document status | Local queue is frontend work; byte progress and finer worker stages need transport/backend support |
| Current actionable activity | Run status, document/session IDs, commands in run detail | Resolve run-to-current-session/material state before deciding what needs action |

Backend remains authoritative for question assignment, prerequisite eligibility, grading, hints, resource publication, and evidence commits. New UI must not compute replacement learner states, expose private tests/rubrics, or turn reading completion into demonstrated evidence.

## Delivery sequence

| Phase | Deliverables | Exit criterion |
| --- | --- | --- |
| 1 — Journey and truth | Connection/save states, phone course switching, URL context, session discovery/summary contract, End session transition | Resume and end-to-summary survive reload and errors without misleading state |
| 2 — Shared UI and core learning | Shared headers/status/components, Today next action, topic lesson navigation, source sheet, practice state hierarchy | Learner can resume, find a lesson, inspect its source, practice, and understand feedback on desktop/phone |
| 3 — Course exploration at scale | Materials library hierarchy, file queue, Progress overview/table/history, compact map/list/details | Current 109-concept course remains easy to browse without enormous prose lists or hidden primary content |
| 4 — Activity and polish | Actionable run overview, URL-backed run details, mobile activity drill-in, typography/accessibility cleanup | Current work and historical traces are clear; all routes pass responsive and keyboard review |

Implement in small vertical slices: add the data contract and states, update the page, verify its journey, then move on. Avoid restyling all screens before the session/resume foundations exist.

Primary files: `frontend/src/components/app-shell.tsx`, `live-workspace.tsx`, `study-materials.tsx`, `related-slides.tsx`, `knowledge-map.tsx`, `agent-activity-workspace.tsx`, `workspace-provider.tsx`, `frontend/src/lib/backend.ts`, and `frontend/src/app/globals.css`. Extract live views into page-focused components as they change. Preserve working legacy fixtures/tests until a separate cleanup confirms they are unused.

## Verification and completion checklist

- Review all seven routes at 1440px desktop, 1024px tablet, and 390px phone; inspect long titles, large math, 109 concepts, long run history, and source sheets.
- Verify empty workspace, empty course, processing-only course, partially ready course, review-required material, and ready course.
- Exercise resume, focused practice, hinted answer, pending assessment, uncertain assessment, confirmed feedback, Next question, and End session → summary. Use isolated test records so UI verification does not alter existing learner evidence.
- Verify lost connection, one-resource failure, uncertain submission retry, stale learner version, duplicate action, failed source preview, empty extracted text, and invalid deep links.
- Check keyboard navigation and focus restoration for dialogs/sheets; test screen-reader names and status announcements; verify no notification flood during polling; inspect contrast, 200% text zoom, and reduced motion.
- Add meaningful behavioral tests for route state, session scoping, save/assessment presentation, course switching, and actionability. Reuse existing backend/bridge coverage for grading, idempotency and eligibility rather than duplicating those policies in UI tests.
- Run the existing test, lint, typecheck, and production build commands after implementation. Visual changes require fresh browser inspection; passing unit tests alone is insufficient.

Completion means a learner can identify a next step on Today, find any lesson by topic/search, consult sources without losing context, complete practice, read a truthful session summary, inspect evidence, and recover from a failure on both phone and desktop.
