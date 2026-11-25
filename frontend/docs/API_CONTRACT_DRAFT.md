# FastAPI Contract Draft

These routes are proposed integration contracts for discussion. They are not implemented or verified backend endpoints. Keep schemas versioned and align exact field names to the audited Splink repository and final PostgreSQL design.

## Health and platform metadata

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/health` | Application/service health |
| GET | `/api/metrics/overview` | Overview metrics for dashboard |
| GET | `/api/activity` | Recent platform events |

## Data sources and datasets

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/sources` | List registered sources |
| POST | `/api/sources` | Register a source profile (no secret in response) |
| POST | `/api/sources/{source_id}/test` | Test a connection server-side |
| GET | `/api/sources/{source_id}/schemas` | Browse accessible schemas/tables |
| POST | `/api/datasets/upload` | Upload a supported file to server-side staging |
| POST | `/api/datasets/from-source` | Register a dataset from a source table |
| GET | `/api/datasets` | List datasets with pagination/filtering |
| GET | `/api/datasets/{dataset_id}` | Dataset metadata and profile |
| POST | `/api/datasets/{dataset_id}/validate` | Validate schema and column mapping |

## Model registry and processing jobs

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/models` | List registered model adapters |
| POST | `/api/models` | Register model metadata / adapter configuration |
| GET | `/api/models/{model_id}` | Model capabilities and version metadata |
| POST | `/api/jobs` | Create and queue a processing job |
| GET | `/api/jobs` | List job history |
| GET | `/api/jobs/{job_id}` | Job status and stage progress |
| POST | `/api/jobs/{job_id}/cancel` | Request cancellation when supported |
| GET | `/api/jobs/{job_id}/results` | Paginated normalized results |
| POST | `/api/jobs/{job_id}/write-output` | Confirm and persist output to an allowed target |

## Review, entities, evaluation, and exports

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/review-queue` | List pending review pairs |
| POST | `/api/review-queue/{pair_id}/decision` | Save human decision and reason |
| GET | `/api/entities` | Browse entity clusters and master records |
| GET | `/api/entities/{entity_id}` | Entity detail and membership |
| GET | `/api/evaluations` | List evaluation runs/metrics |
| POST | `/api/evaluations` | Run evaluation using a named label set |
| GET | `/api/exports/{export_id}` | Export status/download metadata |

## Job submission example (draft)

```json
{
  "name": "Customer deduplication - Q4",
  "dataset_id": "ds_0142",
  "model_id": "mdl_0001",
  "model_version": "resolved-by-registry",
  "configuration": {
    "date_order": "dmy",
    "review_policy": "manual",
    "preserve_source": true
  },
  "output": {
    "mode": "postgres_table",
    "target": "di_results.customer_linkage"
  }
}
```

The example is illustrative. Do not hardcode fields until the adapter and existing repository input contract are audited.

## Response conventions

- Use stable IDs rather than display names as identifiers.
- Return timestamps in ISO 8601 with timezone.
- Include pagination metadata for list endpoints.
- Include structured error codes and actionable messages.
- Include a `run_id`, model/version reference, and config snapshot in execution outputs.
- Use a standardized decision vocabulary only where the selected adapter supports it. For the first Splink engine, expected decisions include `MATCH`, `REVIEW`, and `NON_MATCH` as documented by the repository.
- Never include database passwords, connection secrets, or private credentials in API responses.
