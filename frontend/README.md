# LearnLoop frontend

Next.js learning workspace connected to the local FastAPI backend. All visible course materials, concepts, agent runs, practice questions, assessments, and progress come from saved backend records. Browser demo fixtures are no longer mounted or used by application routes.

## Agent code ownership

The three executing agents live in [`backend/learnloop/agents/`](../backend/learnloop/agents/): **Expert**, **Tutoring** (Tutor in the interface), and **Assessing** (Reviewer in the interface). This frontend displays their public activity; [`src/lib/agent-activity/`](src/lib/agent-activity/) contains event contracts, reducers, and backend/demo display adapters. See the [architecture and class walkthrough](../backend/docs/agent-architecture.md) to follow the actual agent implementations and shared runtime.

## Run

First complete the [SQLite teammate setup](../README.md#local-setup-for-teammates-sqlite) for the API, worker and model services. Node.js 20.9 or newer and npm are required. From the project root, create the local connection file on first setup:

```powershell
Copy-Item frontend/.env.example frontend/.env.local
```

Edit `.env.local` as described below before starting Next.js. Preserve an existing local configuration. From `frontend/`:

```powershell
npm ci
npm run dev
```

Open [Materials](http://127.0.0.1:3100/materials) on this computer. The dev and production Next.js scripts bind to all network interfaces. For optional LAN testing, use your own machine's LAN address and update `allowedDevOrigins` in `next.config.ts` for that host; its existing addresses are specific to the original development machine. Allow inbound TCP port 3100 through your private-network firewall if needed. Create a course, select it in the sidebar, and upload text PDFs or UTF-8 `.txt` files. Multiple files are supported, with a limit of 20 MiB per file and 200 pages per PDF. Scanned PDFs require OCR before upload.

The API and durable worker must also be running; see `../backend/README.md`. Upload receipts mean the file is saved. Processing continues in the worker, and status refreshes automatically every four seconds. Published resources become available in Learn, My understanding, and Progress. Review-required resources remain unavailable for practice; manual approval is not yet supported by the backend.

## Private connection

Configure the ignored `frontend/.env.local`:

```dotenv
LEARNLOOP_BACKEND_URL=http://127.0.0.1:8010
LEARNLOOP_API_TOKEN=PASTE_THE_API_TOKEN_FROM_BACKEND_ENV
```

Replace the placeholder with the exact `API_TOKEN` from your own `backend/.env`, not the OpenRouter key. These are server-only variables. Never use `NEXT_PUBLIC_*` for the token. Restart Next.js after changing configuration. Each teammate must create this ignored local file; it is not supplied by Git.

The `/api/backend/[...path]` route forwards only allowed API paths, attaches the bearer token on the server, checks the origin of writes, and preserves multipart bodies, backend errors, and SSE streams. The browser never receives the backend token. This is a local single-owner workspace; multi-user authentication is outside the current backend contract.

## Real learning flow

Learn has **Study lessons** and **Practice tests** modes. The study view follows ThreadLearn's lesson-first approach: explanations, mathematical formulas, worked examples, takeaways, common mistakes, and flashcards with hidden backs. Original cited slides remain alongside the lesson. The Expert prepares lessons and two private test questions per concept during upload processing; the Tutor selects eligible tests using saved progress and prerequisites. Existing uploads have a **Generate lessons and tests** action. Completed lessons appear progressively and survive generation retries. Expert concept discovery now reviews every extracted passage in sections and merges overlapping goals, so the count adapts to the material. Existing sampled uploads offer **Review all sections and expand lessons**; Materials reports full passage/section coverage after review.

Lessons use short post-style writing: one clear opening, 3–6 bullet points with optional bold labels, short sentences, and a worked example. Safe Markdown/math rendering preserves the post structure. **Refresh lesson formatting** upgrades older material while preserving private tests and learner progress. Completed rewrites appear automatically.

Worked examples use numbered steps with a title, brief explanation, and separate display equations for the formula, numerical substitution, and result. Calculations include the given values, rounding/clipping decisions, and an interpretation of the result. Conceptual steps need no equations. Legacy text steps remain readable. Material version 3 upgrades only the worked example of an existing version 2 short post; it retains every other lesson field and the private test bank. `backend/scripts/validation/worked_examples.py` can start the durable upgrade and compare the saved graph, lesson prose, tests and learner state against its before-state. Long formulas scroll within their equation row on narrow screens.

Learn shows compact task status beside the current action instead of a course-wide run history: question preparation at the practice card, hint/save/checking status by the question controls, and material preparation above study lessons. Idle and completed tasks disappear. Session run IDs and run timestamps prevent historical failures from appearing as current blockers; preparation failures are shown only for a material that still lacks resources. Retry/Resume follows the backend's advertised commands, while **View activity** opens the relevant run on Agent activity. Detailed history lives on that page. Three original local SVG agent portraits identify the Expert, Tutor and Reviewer in lessons, practice, feedback and the activity team cards; they have no external image dependency.

**Practice with your tutor** requests the selected lesson's `conceptId`, opens the practice card, and scrolls it into view. Focused practice stays on that concept when choosing Next question; it never silently chooses another topic. Prerequisite or in-progress assessment conflicts show a clear message with a route back to the lesson. Unanswered questions remain saved and can be restored when returning to their topic. Cited slides use accessible page bubbles with a selected state; both bubble clicks and the viewer's page arrows keep the highlight in sync.

- Materials creates courses and uploads files to SQLite-backed processing jobs. Identical content reuses the original material.
- Agent activity discovers real runs and shows public task details, validation, and advertised retry/resume controls.
- Learn starts or resumes backend sessions, records hints, submits answers with stable operation IDs, and polls the current session for assessment results. The answered question, selected answer, related slides, and analysis stay visible until **Next question** is clicked. Only that action requests a new question and clears the previous analysis. The backend controls question selection, grading, and progression.
- My understanding displays an interactive knowledge map of real published concepts and prerequisite arrows, with difficulty-specific evidence colors, search/material/state filters, zoom and pan, and a concept list. The Expert can organize existing courses into topic groups and review cross-section connections through **Organize course map**. Topic navigation follows the teaching sequence, solid prerequisite arrows are distinct from selected-concept dashed related links, and the details panel explains each relationship. Related links never gate practice. Selecting a concept shows readiness, connected concepts, original source slides, and a link to its study lesson.
- Progress displays server evidence and saved assessment history.
- Source links load extracted document passages from the backend.
- Learn shows the original cited PDF slide in a related-slides panel, with page navigation, Fit/150%/200% zoom, and optional extracted text. On narrow screens, slides appear below the question. If no source was cited, the panel explicitly offers material browsing instead. Materials also supports inline page previews.

The browser stores only the selected course ID. Earlier demo storage is ignored. Legacy fixture/reducer modules remain as unused source references, with their existing tests; they do not contribute to the live workspace.

## Checks

```powershell
npm test
npm run lint
npm run typecheck
npm run build
```

Bridge tests cover private bearer attachment, multipart preservation, streamed responses/cursors, route restrictions, origin rejection, and unavailable-backend errors. The backend's isolated live smoke test exercises real upload processing, retrieval, tutoring, assessment, and evidence persistence while cleaning up its own temporary records and vectors.


The knowledge map offers a 2D learning pyramid (default), the topic atlas, and a 3D topic explorer. The explorer uses native SVG sphere projection with no WebGL or external rendering dependency. Layer, layout and existing filters persist in map URLs. Mobile entry uses 2D; list view remains available. Unassigned legacy concepts remain explicitly unassigned.


The 3D explorer follows the Option C design: overlapping perspective terraces in sage, amber and peach, raised circular topic discs, and a separate white **Topic focus** card. Its default overview fits six Basic, five Intermediate and three Advanced topics without shrinking the discs. Connection endpoints reserve slots independently of pagination; any extra rows fill their remaining slots with browsable topics. The page size and terrace height remain stable while paging, and ordinary topics do not repeat between pages. Per-layer page controls and the full topic directory reach every group; selecting or searching a topic reveals its family across the layer pages and aligns it through the terraces. Every published topic receives a disc on each relevant layer; each concept appears in its primary published topic and actual curriculum layer. The overview supports zoom, background panning, **Focus layer**, reset and a searchable directory of every topic group. The focus panel has family layer tabs, an expandable view and a searchable concept list. Missing memberships remain in **Other concepts**. The 2D pyramid and topic atlas retain their existing layouts.


The focus card opens with a labelled **Topic atlas** disc, an About this topic summary and a direct lesson action. The **Globe** mode retains spherical rotation with faded rear concepts; **Concept list** opens the complete searchable list. Drag a topic disc or the focus canvas to rotate; the selected topic and its miniature stay synchronized. Search and **Locate** reveal the correct topic page and highlight the concept in the foreground; Globe mode brings it exactly to the front, including rear or polar positions. Labels remain upright; local search filters the complete list. Small bubbles on both the terraces and focus panel open a preview on hover/focus. Click/Enter selects the concept and traces its direct published prerequisites, dependents and related concepts. Solid arrows retain prerequisite direction; dashed related links do not imply prerequisites. The preview and focus card retain explicit lesson actions. Touch taps select the connection view; lessons remain available from the focus card. Actual prerequisite relationships appear for the selected concept and in **Learning connections**.

**Auto-rotate** is opt-in and rotates only the selected topic slowly. Motion pauses during globe hover, keyboard focus, dragging, previews, search, list mode, open dialogs and hidden tabs. System reduced-motion preferences disable automatic rotation while keeping manual drag, arrow keys, rotation buttons and reset available. Animation frames, subscriptions and preview timers are cleaned up on unmount. Geometry tests cover search targeting through 1,000 sphere positions and unique topic/layer membership for 900 concepts in 90 groups.


Each topic disc has independent drag rotation, retained when selecting other topics or paging away and back. Dragging rotates in place without selecting or relocating the disc. Connection arrows use small-bubble coordinates and follow their rotation, including links inside one topic. A selected connection view pins every endpoint and its topic on the true curriculum layer, independently of topic pagination and search filters. Extra topics occupy additional terrace rows; **Fit connections** frames the complete set, and **Clear connections** releases it. Paging can change the surrounding topics without removing the pinned nodes or links.


Concept selection uses a 620 ms eased transition for topic positions, terrace expansion, concept positions in both views and overview zoom. Arrow geometry is recomputed from the same interpolated small-bubble coordinates on every frame, so connections remain attached during movement. Newly revealed concepts fade in from their own topic centre; selecting another concept restarts from the currently displayed frame. Direct dragging and rotation controls cancel the transition. **Animate selection** follows the system reduced-motion preference by default and offers an explicit per-view override. Hidden tabs and unmounting cancel animation frames.

The pyramid uses fixed tier positions and three view presets: Default, More overhead, and Front. Background dragging and keyboard arrows pan; scrolling and +/- zoom within a fixed viewport. Home or Reset view restores the default preset and position. Free orbit and tilt sliders are removed. Tier headings and topic labels remain upright and keep their proportions across presets; topic-disc rotation remains independent.


Assessment evidence and mastery targets follow the published curriculum layer: Basic uses Basic, Intermediate uses Intermediate, and Advanced uses Advanced. The map no longer has a separate evidence-difficulty selector. Assigned concepts have a fixed, matching target; unassigned legacy concepts retain their saved target (Intermediate fallback). Existing evidence remains at its original difficulty, including pending activities, and is never relabelled or deleted. Older catalog targets are resolved at read time, preserving source/resource signatures and learner versions. Practice may still adapt down for support, while mastery and prerequisite readiness require evidence at the curriculum layer.
