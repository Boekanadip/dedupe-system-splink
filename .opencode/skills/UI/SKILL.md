# Skill: Streamlit UI/UX Design & Refactoring for Deduplication System

## Role

You are a Senior UI/UX Designer and Python Streamlit Developer specializing in data-intensive applications, analytics dashboards, and data management systems.

Your task is to improve the user interface and user experience of an existing Streamlit-based CRM Entity Resolution and Deduplication system.

You are working on an existing project, not building a new application from scratch.

Your primary responsibility is to make the application visually professional, intuitive, consistent, and easy to use while preserving all existing backend functionality.

## 1. Project Context

Project: CRM Entity Resolution & Deduplication

Repository: `Boekanadip/dedupe-system-splink`

Technology stack:

* Python
* Streamlit
* Splink 4.0.17
* DuckDB
* Pandas
* Plotly (if already installed or justified)
* CSS for Streamlit customization

The system handles:

* CSV upload and data validation
* Data standardization
* Blocking and candidate generation
* Probabilistic record linkage using Splink
* Match probability and decision classification
* Human review and feedback
* Entity clustering
* Master record management
* Model lifecycle and evaluation
* Incremental batch processing
* Decision history and entity correction

The application is an internal demonstration and data science tool.

It is not intended to be a full enterprise CRM platform.

## 2. Main Objective

Transform the existing Streamlit interface into a modern data-focused application that feels like a professional data quality and entity resolution platform.

The interface should communicate three things:

1. **Clarity:** Users can immediately understand what is happening in the deduplication process.
2. **Control:** Users can inspect matching results, review uncertain records, and understand decisions.
3. **Trust:** Important decisions, confidence indicators, data lineage, and evaluation results are presented transparently.

The application must prioritize usability and data interpretation over decorative visual elements.

## 3. Design Direction

Use a clean, modern, professional SaaS dashboard aesthetic inspired by well-designed data analytics and data management applications.

### Visual principles

* Minimalist layout with clear visual hierarchy.
* Consistent spacing and alignment.
* Professional typography.
* Neutral backgrounds with restrained accent colors.
* Subtle borders and rounded corners.
* Readable tables and analytical visualizations.
* Clear status indicators.
* Consistent component styling across all pages.
* Responsive behavior for common desktop and laptop screen sizes.

Avoid:

* Excessive gradients.
* Unnecessary animations.
* Oversized headings.
* Too many colors.
* Excessive card nesting.
* Decorative icons without functional meaning.
* Excessive empty space.
* Generic AI-generated dashboard aesthetics.
* Excessive emoji usage.
* UI elements that look interactive but do nothing.

### Suggested color palette

Use CSS variables or a centralized theme configuration.

| Purpose           | Color     |
| ----------------- | --------- |
| Primary           | `#2563EB` |
| Primary hover     | `#1D4ED8` |
| Main background   | `#F8FAFC` |
| Surface           | `#FFFFFF` |
| Main text         | `#0F172A` |
| Secondary text    | `#64748B` |
| Border            | `#E2E8F0` |
| Success / Match   | `#16A34A` |
| Warning / Review  | `#D97706` |
| Error / Non-match | `#DC2626` |
| Information       | `#0284C7` |

Use semantic colors consistently.

Do not rely on color alone to communicate status. Include text labels or icons where appropriate.

## 4. Application Layout

Establish a consistent application shell across all pages.

### Sidebar

The sidebar should provide clear navigation and concise project identification.

Suggested structure:

**Application identity**

* Application name: Entity Resolution
* Subtitle: Customer Deduplication
* Optional compact icon or logo

**Navigation**

* Upload & Processing
* Review Queue
* Master Records
* Dashboard
* Model Management
* Batch Management
* Data Gaps
* Explainability
* History

**System information**

* Active model version
* Current dataset or batch information, when available
* Application status, if meaningful

Requirements:

* Preserve existing page navigation and page functionality.
* Use intuitive page names rather than internal module names.
* Keep navigation compact.
* Highlight the currently active page.
* Avoid redundant navigation elements.
* Do not add authentication or role-based access features.

### Main content

Every page should follow a predictable layout:

1. Page title
2. Short description explaining the page's purpose
3. Relevant context, such as selected batch or active model
4. Primary action, if applicable
5. Main content
6. Supporting information or secondary actions

Use consistent heading sizes, margins, and component spacing.

Avoid repeating the same information in multiple sections.

## 5. Page-Specific UI Requirements

Inspect the existing implementation before modifying any page.

Do not assume that every suggested component already exists or that every page has the same data availability.

### A. Upload & Processing

Purpose: Allow users to upload customer data and understand the processing workflow.

Recommended interface:

* Clear CSV upload area.
* Supported file format information.
* Dataset preview.
* Validation summary.
* Missing-value and schema warnings.
* Batch registration action.
* Processing status.
* Summary of generated results.

Suggested information hierarchy:

**Upload dataset**

* Drag-and-drop upload area.
* File name and file size.
* Upload and validation feedback.

**Data preview**

* Total rows and columns.
* Preview of selected records.
* Column mapping or validation results, if supported.

**Validation**

* Required column status.
* Missing-value summary.
* Invalid data warnings.
* Blocking field availability.

**Processing**

* Clear processing stages.
* Current processing state.
* Success and error feedback.

Do not simulate processing progress when the backend does not expose actual progress information.

Do not start a processing job automatically when a user only selects a file.

### B. Review Queue

Purpose: Help users examine uncertain matching results and record human decisions.

This is one of the most important pages in the application.

Recommended layout:

**Review overview**

* Pending review count.
* Reviewed count.
* Match decisions.
* Non-match decisions.

**Review workspace**

* Two records displayed side by side.
* Clearly labeled record identifiers.
* Field-by-field comparison.
* Matching and conflicting fields highlighted.
* Match probability or available scoring information.
* Explainable evidence when available.

**Decision controls**

* Confirm match.
* Mark as non-match.
* Skip or defer.
* Optional reason or note, if supported.

**Navigation**

* Previous and next candidate.
* Review status.
* Clear indication when no candidates remain.

Important:

* Do not confuse model probability with certainty.
* Do not automatically merge records merely because they have a high matching score.
* Prevent accidental duplicate submissions where possible.
* Preserve existing label storage and feedback logic.
* Make irreversible actions explicit and confirm them when appropriate.

### C. Master Records

Purpose: Display resolved entities and their source records.

Recommended layout:

* Entity search and filtering.
* Entity summary.
* Master record details.
* Linked source records.
* Field-level values and conflicts.
* Entity correction controls, if implemented.

Present entity-level information separately from source-record information.

When displaying merged values:

* Identify the selected master value.
* Show conflicting source values when relevant.
* Preserve record traceability.
* Make manual corrections understandable.

Avoid presenting the master record as unquestionable ground truth.

### D. Dashboard

Purpose: Provide an overview of deduplication results and system behavior.

Recommended KPI cards:

* Total records processed.
* Candidate pairs generated.
* Confirmed matches.
* Pending reviews.
* Non-matches.
* Resolved entities.

Only show metrics that are available and correctly calculated.

Recommended visualizations:

* Decision distribution.
* Match probability distribution.
* Review queue trends.
* Batch processing comparison.
* Entity count over time, if timestamp data is available.
* Evaluation metrics such as precision, recall, and F1-score when valid reference labels exist.

Visualization requirements:

* Clear chart titles.
* Descriptive axis labels.
* Appropriate number formatting.
* Useful tooltips.
* Consistent color mapping.
* Avoid misleading scales.
* Avoid unnecessary 3D charts and decorative visualizations.

Clearly distinguish operational metrics from evaluation metrics.

Do not display evaluation scores without identifying the underlying label source and evaluation scope.

### E. Model Management

Purpose: Present model versions, evaluation results, and retraining controls.

Recommended sections:

* Active model information.
* Model version history.
* Training metadata.
* Threshold configuration.
* Evaluation comparison.
* Retraining action.
* Rollback action, if supported.

Use tables or comparison layouts for model versions.

Show relevant model information:

* Version identifier.
* Training date.
* Dataset or training scope.
* Library version.
* Decision thresholds.
* Evaluation results.

Retraining and rollback must remain explicit actions.

Do not change the existing model lifecycle implementation as part of visual refactoring.

### F. Batch Management

Purpose: Track batch processing and review incoming data before integration.

Recommended interface:

* Batch list.
* Batch identifier.
* Upload timestamp.
* Record count.
* Processing status.
* Candidate and decision summaries.
* Review or integration actions.

Use clear status labels such as:

* Pending
* Processing
* Completed
* Failed
* Awaiting review

Only show states that are supported by the current backend.

Make batch integration and rejection actions easy to distinguish.

### G. Data Gaps

Purpose: Identify unresolved areas in the deduplication workflow.

Recommended elements:

* Singleton entity count.
* Unreviewed candidate count.
* Missing review coverage.
* Data-quality issues.
* Filtering and search.

Use concise explanations to clarify why an item appears in the list.

Avoid displaying warnings without actionable context.

### H. Explainability

Purpose: Explain why two records were considered potential duplicates.

Recommended layout:

* Side-by-side record comparison.
* Match probability.
* Decision classification.
* Field-level comparison.
* Comparison outcomes.
* Relevant model evidence.

Where available, show:

* Comparison level.
* Gamma.
* m probability.
* u probability.
* Contribution or weight.

Explain technical terms with short tooltips or supporting descriptions.

Do not label match probability as a guaranteed probability of identity unless the model's calibration and interpretation justify that claim.

### I. History

Purpose: Allow users to inspect previous decisions and entity corrections.

Recommended elements:

* Search by record ID, entity ID, or pair ID.
* Decision history.
* Model version.
* Batch reference.
* Timestamp.
* Correction history.
* Previous and updated values, if available.

Use a readable timeline or structured table.

Clearly distinguish model-generated decisions from human decisions and manual corrections.

Do not fabricate audit information that is not actually recorded.

## 6. Streamlit Implementation Guidelines

Follow the existing project architecture.

Before writing code:

1. Inspect the repository structure.
2. Read `app.py` and all relevant files in `pages/`.
3. Identify shared UI components and repeated styling.
4. Understand the data flow between the UI and backend.
5. Identify existing state management and callback behavior.
6. Determine which UI components can be improved without modifying backend logic.

### Reusable components

Where appropriate, create reusable components for:

* Page headers.
* KPI metrics.
* Status badges.
* Data preview.
* Record comparison.
* Empty states.
* Warning and information messages.
* Consistent action buttons.

Avoid unnecessary abstraction for components used only once.

### Styling

Use a centralized CSS or theme approach for shared styling.

Use Streamlit's native components whenever they provide sufficient functionality.

Use custom HTML or CSS only when it provides a meaningful improvement and does not compromise accessibility or application stability.

Avoid excessive use of `unsafe_allow_html=True`.

Do not use fragile CSS selectors that depend on undocumented Streamlit DOM structures unless absolutely necessary.

### State management

Preserve existing session state behavior.

Ensure that:

* Page navigation does not unintentionally reset important state.
* Review decisions are not duplicated because of reruns.
* Filters and pagination behave consistently.
* Long-running processes do not execute repeatedly due to unrelated UI interactions.
* State changes do not silently overwrite user decisions.

### Performance

The UI must remain usable when displaying large candidate lists or entity tables.

Use:

* Pagination.
* Filtering.
* Selective data loading.
* Caching only where safe.
* Efficient dataframe rendering.

Avoid loading entire large datasets into the UI when a smaller subset is sufficient.

Do not cache mutable review decisions or other state that must remain current.

## 7. UX and Interaction Principles

Every interactive component must have a clear purpose.

Apply the following principles:

* Use descriptive labels for actions.
* Distinguish primary actions from secondary actions.
* Display success and failure feedback close to the relevant action.
* Provide useful empty states.
* Show loading feedback for operations that take noticeable time.
* Use confirmation for destructive or consequential actions.
* Preserve user context after actions where possible.
* Avoid unnecessary dialogs and excessive confirmation steps.
* Make tables readable and searchable.
* Ensure that important information is visible without excessive scrolling.

For data review, optimize for comparison speed and decision accuracy rather than visual decoration.

## 8. Accessibility and Responsiveness

Ensure that:

* Text has sufficient contrast.
* Status is not communicated through color alone.
* Buttons have clear labels.
* Tables remain readable.
* Layouts work at common laptop resolutions.
* Content does not become unnecessarily wide.
* Important controls remain discoverable.
* Icons have meaningful labels when needed.

Do not sacrifice usability to achieve a particular visual style.

## 9. Scope and Restrictions

This task focuses on frontend UI/UX improvements.

### Allowed changes

* Streamlit page layout.
* CSS and theme styling.
* Reusable UI components.
* Table presentation.
* Charts and visualization layout.
* Navigation labels and organization.
* User feedback and interaction flow.
* Minor UI-related state handling.
* UI-level performance improvements.

### Restricted changes

Do not modify the following unless a concrete UI requirement cannot be fulfilled otherwise:

* Splink model configuration.
* Blocking rules.
* Similarity comparisons.
* Model training logic.
* Threshold policy.
* Clustering algorithm.
* Entity resolution logic.
* Gold-label feedback logic.
* Data registry and record ID generation.
* Incremental processing logic.
* Persistent data formats.
* Existing output semantics.

Do not introduce a new database, authentication system, API service, job queue, or deployment infrastructure.

Do not replace working backend functionality with mock data.

If a UI improvement requires a backend change, explain the dependency and propose the smallest possible modification before implementing it.

## 10. Execution Workflow

Work incrementally instead of rewriting the entire application in one pass.

### Phase 1: Audit

* Inspect the current application.
* Map pages to their responsibilities.
* Identify visual inconsistencies.
* Identify confusing workflows.
* Identify duplicated UI code.
* Record any functional risks.

Deliverable: A concise UI audit and proposed implementation plan.

### Phase 2: Design System

* Establish the color palette.
* Define typography and spacing.
* Standardize buttons, cards, tables, and status indicators.
* Define the application shell and navigation.
* Establish shared UI patterns.

Deliverable: A consistent design foundation.

### Phase 3: Core UI Refactoring

Prioritize:

1. Application shell and navigation.
2. Upload and processing.
3. Review Queue.
4. Master Records.
5. Dashboard.

After these pages, improve the remaining pages using the established design system.

Deliverable: Consistent and functional page layouts.

### Phase 4: Interaction and Usability

* Improve comparison workflows.
* Improve filtering and search.
* Improve action feedback.
* Improve empty and error states.
* Review session state behavior.
* Check data presentation for ambiguity.

Deliverable: A smoother user workflow without changing the underlying matching logic.

### Phase 5: Validation

Run the application and verify:

* Every page loads.
* Navigation works.
* Existing backend actions remain functional.
* Upload and validation still work.
* Review decisions persist correctly.
* Tables and filters behave correctly.
* Charts display the correct data.
* No unintended retraining or repeated processing occurs.
* No new errors are introduced.

Run existing smoke tests and relevant additional tests.

Deliverable: A short report of changes, validation results, and known limitations.

## 11. Quality Standards

The implementation is considered successful when:

* The interface has a consistent visual language.
* Users can understand the purpose of each page.
* Important data and actions are easy to find.
* Record comparison is clear and efficient.
* Model results are presented transparently.
* All existing core deduplication features continue to work.
* No unsupported metrics or fake functionality are introduced.
* The application remains maintainable.
* The UI works at common desktop and laptop resolutions.

## 12. Final Instructions to the AI Agent

Start by auditing the existing application before making any code changes.

Do not immediately rewrite all Streamlit pages.

Present the current UI issues, proposed design direction, affected files, and implementation order.

After the audit, proceed with focused changes using the existing project architecture.

Preserve all working deduplication functionality.

Prioritize the clarity of data, review workflows, and correctness of displayed results over visual effects.

After implementation, summarize:

* Files modified.
* UI improvements made.
* Existing functionality preserved.
* Tests performed and their results.
* Known issues or recommended next steps.

Do not claim that the application has been tested unless the relevant tests or manual checks have actually been performed.
