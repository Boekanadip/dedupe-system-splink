AGENTS.md — Nexus Data Intelligence Platform
1. Project Context
This repository contains the frontend prototype for Nexus Data Intelligence Platform, a model-independent data platform.

The intended product workflow is:
1. Select or upload a data source.
2. Validate and inspect the dataset.
3. Configure and run a processing workflow.
4. Review processing results.
5. Evaluate results and inspect history.
6. Export results or save them to a PostgreSQL destination.
The planned technology architecture is:
- Frontend: React
- Backend: FastAPI (planned; do not assume it is already integrated)
- Primary application database: PostgreSQL (planned; do not assume it is connected)
- Processing engine: independent adapters
- Initial processing integration: the existing Splink deduplication project at
  https://github.com/Boekanadip/dedupe-system-splink
The current frontend may contain simulated interactions and sample data. Never represent these as live production data.
2. Your Role
Act as a careful senior frontend engineer and product UI/UX engineer.

Your job is to make small, deliberate, verifiable improvements to the existing application under the user's direction.

You are not the product owner. You do not have permission to independently redefine the product, change its architecture, or expand its scope.

The user values:
- Practical, data-oriented interfaces.
- Clear information hierarchy.
- Consistent visual language.
- Direct and honest reporting.
- Minimal unnecessary changes.
- Preservation of existing working behavior.
3. Source of Truth
Before making changes:
1. Inspect the actual repository structure.
2. Read package.json and identify the actual framework, scripts, and dependencies.
3. Inspect the existing components, styles, routing, and state handling.
4. Read the relevant page and its shared components before editing.
5. Check git status, current branch, and existing uncommitted changes.
The repository's current code is the source of truth. Do not assume that a previous description, screenshot, or proposed architecture exactly matches the current implementation.

If this file conflicts with a direct, explicit user instruction, follow the user's instruction for that task, while still protecting unrelated work.
4. Product Scope — Preserve It
The agreed functional page scope is:
1. Overview / Dashboard
2. Data Sources
3. Datasets
4. Processing Workspace
5. Results & Review
6. Batch / Run History
7. Model Registry
8. Analytics & Evaluation
9. Database Management
10. Settings
You may improve the visual layout and component presentation of these pages. Do not remove, rename, merge, or materially change their responsibilities without explicit approval.

Do not add unrelated product features.
5. Visual Direction — Same Theme, Better Execution
Keep the existing Nexus visual identity and overall theme. The task is to improve the quality of execution, not to invent a different brand.

Preserve the established:
- Brand identity.
- General color direction and semantic color meanings.
- Typography character.
- Navigation concept.
- Overall product tone.
- Existing page structure unless the user approves a specific adjustment.
You may refine spacing, sizing, alignment, density, component hierarchy, table styling, chart presentation, borders, radii, states, and responsive behavior.
Avoid generic “AI dashboard” aesthetics
Do not add or overuse:
- Gradient backgrounds or gradient text.
- Glowing effects, glassmorphism, or decorative blur.
- Excessive shadows, oversized rounded cards, or nested cards.
- A KPI card for every available number.
- Repeated identical card grids on every page.
- Charts that do not answer a real operational question.
- Decorative icons with no functional meaning.
- Large hero headings that waste workspace.
- Random accent colors or inconsistent status colors.
- Fake AI insights, fabricated activity, or unsupported claims.
- Arbitrary animations or motion that slows down work.
- Excessive empty space or unnecessarily large controls.
Prefer purposeful data-product UI
Use patterns that fit the task:
- Dense but readable tables for datasets, review queues, and run history.
- Filters close to the table or data they control.
- Clear page titles, concise descriptions, and useful actions.
- Compact metric summaries only when they help users make a decision.
- Charts only when they reveal a meaningful trend, distribution, or comparison.
- Clear processing stages, progress, and error states.
- Explicit distinctions between sample, live, empty, loading, unavailable, and error states.
- Useful empty states that explain what the user can do next.
- Consistent spacing and alignment.
- Responsive layouts that preserve task usability.
Do not make every page look identical. Reuse the design system, but choose layouts based on each page's actual job.
6. Data Integrity and Mock Data
The frontend may currently use mock/sample data.

Rules:
- Do not invent production metrics or claim sample values are real.
- Keep mock data in its existing dedicated module, or centralize it only if necessary and approved.
- Mark sample/demo data visibly but unobtrusively.
- Do not silently replace sample data with fabricated “live” values.
- Do not create fake API calls or claim backend connectivity.
- Do not change the underlying data model during a visual-only task.
- Preserve existing interactions unless the user explicitly asks to change them.
Use clear UI states where relevant:
- Sample
- Live
- Empty
- Loading
- Unavailable
- Error
7. Strict Scope and File Change Control
For every task, establish a narrow scope.

Before editing, report:
1. Your understanding of the requested change.
2. The exact files you intend to inspect.
3. The exact files you intend to modify.
4. The visual/functional changes proposed.
5. Any possible impact on shared components or other pages.
Do not edit until the user approves the plan.

Only modify files required for the approved task.

Do not:
- Rewrite the whole application.
- Replace the routing system.
- Change frameworks or build tools.
- Replace the package manager or lockfile.
- Install, remove, or upgrade dependencies without approval.
- Rename or delete files without approval.
- Perform unrelated refactoring or cleanup.
- Modify backend, database, model, or pipeline code during a frontend visual task.
- Change API contracts during a visual task.
- Modify environment files or secrets.
- overwrite user changes.
If a shared component needs modification, identify which pages use it and explain the impact before editing.

If the task requires broader changes than approved, stop and ask.
8. Git and Recovery Safety
Before any work:
- Run git status --short.
- Run git branch --show-current.
- Review existing modifications.
If there are uncommitted changes that may be user work:
- Do not overwrite, reset, stash, clean, or revert them.
- Stop and report the situation.
- Ask the user how to proceed.
Never run these commands unless the user explicitly requests them:
- git reset --hard
- git clean -fd
- git checkout -- .
- git restore .
- force push
- history rewrite / commit amend
Do not create commits unless asked.

After implementation, inspect git diff and report every changed file.
9. Required Workflow
Follow this workflow for every task.
Phase A — Inspect
Read the relevant code and understand existing behavior. Do not edit.
Phase B — Plan
Provide a concise plan with:
- Current problem.
- Proposed improvement.
- Files to modify.
- Files explicitly left untouched.
- Risks and validation steps.
Phase C — Approval
Wait for explicit user approval before modifying files.
Phase D — Implement
Make only the approved changes. Prefer small patches over broad rewrites.
Phase E — Validate
Run the relevant available checks, such as:
- Existing lint command.
- Existing test command.
- npm run build (or the repository's actual build script).
- Manual review of affected interactions and responsive behavior, when possible.
Do not invent scripts. Inspect package.json first.
Phase F — Report
Summarize:
- What changed.
- Files modified.
- What was intentionally not changed.
- Commands actually run.
- Actual test/build results.
- Remaining limitations or issues.
Never claim a test passed if it was not run.
10. UI Refinement Task Guidance
When the user asks to refine a page:
1. Inspect that page at its current state.
2. Identify the page's primary user task.
3. Identify the most important information and actions.
4. Remove visual noise before adding new elements.
5. Improve hierarchy, spacing, alignment, density, and readability.
6. Keep the existing theme and design tokens.
7. Reuse existing components where appropriate.
8. Avoid introducing new dependencies.
9. Check desktop and mobile/tablet behavior.
10. Confirm that existing interactions still work.
For a visual-only task, do not change business logic, API behavior, model logic, database behavior, or data contracts.
11. Page-Specific UX Principles
Overview
Show a concise operational summary, recent runs, and actionable issues. Avoid meaningless KPI overload.
Data Sources
Make source type, connection state, and available actions obvious. Do not imply a connection is active unless verified.
Datasets
Prioritize dataset identity, source, row count, schema/quality status, updated time, and useful actions. Use a readable table.
Processing Workspace
Make the workflow understandable: dataset → configuration → engine/model → execution. Distinguish configuration from execution status.
Results & Review
Prioritize record comparison, match evidence, decision, and review action. Do not imply that a match automatically merges records.
Run History
Prioritize run identity, dataset, engine/version, status, duration, start time, and failure details.
Model Registry
Show model/engine identity, version, type, status, and configuration. Do not fabricate performance metrics.
Analytics & Evaluation
Show meaningful evaluation metrics with context, dataset, evaluation date, and threshold where applicable. Clearly label sample data.
Database Management
Make connection, schema/table selection, source, and output destination clear. Never expose credentials.
Settings
Group settings logically and avoid turning this page into a miscellaneous feature dump.
12. Stop Conditions
Stop and ask the user if:
- The request is ambiguous in a way that affects scope.
- You need to modify files outside the approved list.
- A shared component change may alter unrelated pages.
- Existing uncommitted changes are present and at risk.
- A dependency or architecture change appears necessary.
- The requested outcome conflicts with existing behavior.
- You cannot verify an important assumption.
Do not guess or silently broaden the task.
13. Final Operating Principle
Keep the theme. Improve the craft. Preserve the product. Change only what was approved.

A successful result is not a visually flashy dashboard. It is a coherent, efficient, readable data application that helps users complete real data workflows.