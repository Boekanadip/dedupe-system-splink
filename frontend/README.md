# Data Intelligence

React + Vite frontend prototype for a model-independent data operations platform. The visual system is intentionally redesigned as a modern enterprise workspace rather than a clone of the previous prototype.

## Current scope

The prototype covers the 10 planned product areas:

1. Overview
2. Data sources
3. Datasets
4. Processing workspace
5. Review queue
6. Run history
7. Model registry
8. Evaluation
9. Database management
10. Settings

### Interactive prototype features

- Sidebar navigation with a compact mode and responsive mobile navigation.
- Light/dark theme toggle.
- Data-source tabs and database-connection placeholder form.
- Local dataset registration when a file is selected.
- Dataset search and validation-status filter.
- Processing-run configuration and a simulated stage-by-stage run.
- Review-pair selection and local `MATCH` / `NON_MATCH` decisions.
- Sample review CSV export.
- Model registry placeholder creation.
- Run-history filtering and illustrative analytics.
- PostgreSQL schema browser and output-destination settings UI.
- Toast feedback and notification popover.

## Run locally

Requirements: Node.js 20+ and npm.

```bash
npm install
npm run dev
```

Open the local URL printed by Vite, normally `http://localhost:5173`.

Production build:

```bash
npm run build
npm run preview
```

## FastAPI integration boundary

Copy `.env.example` to `.env` and set the backend URL when an API is available:

```env
VITE_API_BASE_URL=http://localhost:8000
```

A small request client and draft endpoint wrappers are provided in `src/services/platformApi.js`. The UI does not automatically call these routes yet. The route list is a proposed API contract, not a statement that the backend exists.

See:
- `docs/ARCHITECTURE.md`
- `docs/API_CONTRACT_DRAFT.md`
- `docs/REPOSITORY_INTEGRATION_NOTES.md`

## Important prototype boundaries

- **No live backend is connected.** The API base URL only configures the future request boundary; a configured URL does not mean the server is reachable.
- **No live PostgreSQL connection is created.** Database connection forms and schema content are illustrative placeholders.
- **No Splink model is executed.** Processing is simulated in the browser. The Splink adapter is marked as pending.
- **No source files are uploaded to a server.** Selecting a file registers its name and size in local React state only.
- **Most dashboard numbers and charts are sample data.** They must not be treated as actual model or business performance.
- **Review decisions are local state only.** They are not written to a review store or audit log.
- **CSV export contains sample review rows from this prototype.** It is not an export from the existing Splink repository.
- **Credentials must never be placed in React or committed to `.env` files.** Production database credentials belong in backend secrets or a secret manager.

## Design direction

- Deep navy workspace navigation with a bright, neutral analytical canvas.
- Manrope headings and DM Sans interface typography.
- Blue for primary actions, mint for positive states, amber for review states, violet for model/engine context, and muted grey for neutral status.
- Dense data tables where needed, with clearer separation between operational workflow and analytics.
- Responsive layouts and a compact sidebar mode.

## Repository relation

The first planned processing-engine integration is based on:

`https://github.com/Boekanadip/dedupe-system-splink`

The public repository README describes a Python, Splink 4, DuckDB, Pandas, PyArrow, and Streamlit deduplication application. Its documented workflow includes validation, internal record IDs, standardization, blocking, probabilistic scoring, `MATCH / REVIEW / NON_MATCH` decisions, human review, clustering, entity IDs, master records, evaluation, feedback, and incremental processing.

The current frontend prototype references that workflow but does not import or modify repository code. The existing Streamlit UI should not be migrated wholesale. The next engineering step is to inspect the actual source modules and extract reusable processing services behind a FastAPI adapter while preserving the existing pipeline behavior.
