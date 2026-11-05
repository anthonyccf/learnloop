# COMP7608 1B Large Language Models

Final Project Guideline

## 1. Project Scope

The final project should focus on Agentic AI: building a working AI system that can reason, plan, use tools, take multiple steps, and complete a user-oriented task.

A valid project should include:

- A clear user problem and motivation.
- A meaningful agentic workflow, where the agent makes decisions and performs multiple actions.
- One or more tools or external resources, such as web search, databases, APIs, code execution, files, or other software tools.
- A working end-to-end system, rather than only a model, prompt, or isolated component.
- Evaluation of the system, such as task quality, reliability, latency, cost, robustness, or other meaningful metrics.
- Runnable code and a discussion of limitations and design trade-offs.

## 2. What Counts as Agentic AI?

The project should demonstrate at least one meaningful agentic capability:

- Planning / task decomposition
- Tool use and tool selection
- Multi-step task execution
- Iterative reasoning and verification
- Interaction with external environments or data
- Memory / state management
- Reflection, self-correction, or error recovery
- Multi-agent collaboration (optional)

Key requirement: the system should do more than generate a response from a single prompt. The agent should play an active role in deciding what to do next and carrying out the task.

## 3. Examples Within Scope

Possible directions include:

- Financial-news research assistant
- Domain-specific RAG agent with source verification
- Data-analysis and visualization agent
- Coding, testing, or debugging workflow agent
- Personal or organizational knowledge assistant
- Web research / information gathering agent
- Literature search and recommendation agent
- Document analysis and report-generation agent
- Customer-support or task-execution agent
- Multi-agent system for collaborative problem solving

These are examples only. Other application domains are welcome as long as the project contains a substantial agentic AI component. If you are unsure whether your proposed topic meets the project requirements, please consult the Instructor or TAs before proceeding.

## 4. Examples Outside Scope

The following are generally not sufficient on their own:

- A simple chatbot with no multi-step task execution
- A basic single-turn LLM application
- A standard RAG pipeline without agentic decision making
- Prompt engineering alone
- Fine-tuning a model without building an agentic application
- A model benchmark without an actual application or system
- A UI/demo that does not contain a meaningful agentic workflow

These components may be used as part of a larger project, but they should not constitute the main contribution.

## 5. Note on model selection and output quality

You may use any suitable language model, including a locally deployed open-source model or a publicly available model accessed through an API. Access to the most advanced commercial models is not required. HKU ITS provides student quota for GenAI APIs. See https://its.hku.hk/services/ai-as-a-service/hku-chatgpt/ for details.

Your LLM or agent does not need to produce perfect results. However, you should systematically evaluate its output quality, discuss observed limitations and failure cases, and explain how the system could be improved. Detailed evaluation requirements will be provided in a separate document.

## 6. Group Formation

- Group size: 3–5 students.
- Self-grouping deadline: 21 September, 18:00.
- Students without a group after the deadline will be randomly assigned.
- Each group should nominate one contact member responsible for communication and submission.
- Private swapping of members is not allowed. Please contact the TAs if a change is necessary.

## 7. Deliverables and Assessment

| Deliverable | Due | Weight | Notes |
| --- | --- | --- | --- |
| Proposal | 9 Oct., 24:00 | 20% | Requirements and template provided separately |
| Report & Code | TBA | 50% | Report requirements and template TBA; runnable code required |
| Presentation | TBA | 30% | Format and requirements TBA |

The proposal template and detailed requirements are provided in a separate file. Detailed requirements for the Report & Code and Presentation will be announced later (TBA).

Build a working agentic application and defend its design.

---

# COMP7608B Project Proposal Guidelines

COMP 7608B Teaching Group

## 1. Submission requirements

Each group must submit one project proposal as a PDF.

- Deadline: October 9, 2026, at 12:00 p.m. (Hong Kong Time). No late submissions will be accepted.
- Length: There is no minimum page requirement. The main content must not exceed four pages. Appendix and References do not count toward the page limit.
- Formatting: Use the NeurIPS 2026 LaTeX template. Page 2 of the proposal document shows the required proposal format.
- Abstract: Do not include an abstract.

## 2. Detailed requirements

The proposal must cover at least the following components. Other relevant components may be included where necessary.

- **Group members.** List all team members with their names and student IDs.
- **Clear project objective.** Define what you aim to achieve.
- **Motivation and challenges.** Explain the problem you are addressing and why it is important.
- **Potential solutions.** Outline your proposed approach and methodology.
- **Experimental dataset description and evaluation plan.** Describe your data sources and how you will measure success.

## Proposal template

1. Group members
2. Project objective
3. Motivation and challenges
4. Potential solutions
5. Experimental dataset description and evaluation plan
