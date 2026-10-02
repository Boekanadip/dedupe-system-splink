# DESIGN.md
# CRM Entity Resolution System

## 1. Architecture Principle

The architecture is divided into layers.

INPUT
 ↓
INGESTION
 ↓
STANDARDIZATION
 ↓
FEATURE ENGINEERING
 ↓
BLOCKING
 ↓
ENTITY RESOLUTION
 ↓
DECISION
 ↓
ENTITY MANAGEMENT
 ↓
FEEDBACK / MONITORING
 ↓
MODEL LIFECYCLE

---

# 2. Suggested Project Structure

Suggested structure:

src/
    ingestion/
    standardization/
    features/
    blocking/
    linkage/
    decision/
    entity/
    evaluation/
    monitoring/

configs/
models/
data/
notebooks/
tests/

execution/
    duckdb/
    spark/

The exact structure may change after inspecting the current repository.

Do not reorganize the entire repository unnecessarily.

---

# 3. Ingestion Layer

Responsibilities:

- read input
- validate schema
- generate record_id
- preserve raw data
- identify source

Input schema should not be hardcoded without configuration.

Different source systems may map their columns into canonical fields.

---

# 4. Canonical Schema

Internally, the system may use canonical concepts such as:

record_id
source_id
first_name
last_name
email
phone
gender
dob
address
city
state
country
device_ids

However, this is a conceptual canonical schema.

The actual production/client schema must be mapped into it.

Do not assume every source contains every field.

---

# 5. Standardization Layer

Raw:

first_name

↓

first_name_std

Raw:

phone

↓

phone_std

Raw:

email

↓

email_std

Raw:

address

↓

address_std

Standardization should be:

- deterministic where appropriate;
- configurable;
- reusable;
- testable;
- source-aware when necessary.

Do not over-normalize.

---

# 6. Feature Engineering Layer

Potential features:

- exact normalized equality
- fuzzy name similarity
- email components
- phone suffix
- address similarity
- token overlap
- missingness
- value length
- blocking keys

Only implement features with a documented purpose.

---

# 7. Blocking Layer

Blocking should be represented as configurable strategies.

Example conceptual configuration:

blocking_rules:
    - exact_email
    - exact_phone
    - name_and_dob
    - name_and_city

This is illustrative only.

Actual rules must be selected after benchmark.

Each blocking strategy should be measurable.

Metrics:

candidate_pairs
reference_pairs
coverage
runtime
block_size

---

# 8. Linkage Layer

Current primary implementation:

Splink.

The linkage layer should expose a relatively stable interface to the
rest of the application.

Conceptually:

input records
    ↓
candidate pairs
    ↓
field comparisons
    ↓
probabilistic scoring
    ↓
pair probability/evidence

The rest of the application should not depend unnecessarily on
Splink-specific internals.

---

# 9. Decision Layer

Input:

pair probability/evidence

Output:

MATCH
REVIEW
NON_MATCH

Thresholds must be configuration-driven.

Do not hardcode thresholds in business logic.

---

# 10. Entity Layer

Responsibilities:

- assign entity_id
- maintain entity membership
- maintain source record relationships
- maintain history
- support master record construction

Entity identity must be independent of source customer_id.

---

# 11. New Data Processing

For a new dataset:

1. ingest
2. assign record_id
3. preserve raw
4. standardize
5. feature engineering
6. dedupe within new batch
7. resolve new entities against existing entities
8. decision
9. entity assignment
10. master/history update

---

# 12. Feedback Layer

Review results should be persisted.

Example conceptual fields:

pair_id
record_id_l
record_id_r
score
decision
human_label
reviewer
timestamp
model_version

This data becomes useful for:

- evaluation
- error analysis
- threshold tuning
- blocking evaluation
- model comparison
- retraining

---

# 13. Model Lifecycle

Models/configuration are versioned.

Example:

models/
    v1/
    v2/
    v3/

Each version should have:

- model/config
- thresholds
- training metadata
- evaluation results
- feature/comparison configuration
- creation timestamp
- version identifier

---

# 14. Production Adaptation

The system should support:

model v1
    ↓
production inference
    ↓
feedback
    ↓
monitoring
    ↓
new reviewed examples
    ↓
retraining
    ↓
model v2
    ↓
offline comparison
    ↓
promotion

Do not automatically promote a retrained model.

---

# 15. Backend Strategy

Current backend:

DuckDB.

Future backend may be distributed depending on scale.

Do not make application architecture depend directly on DuckDB-specific
implementation wherever avoidable.

Potential future:

Python + Splink + Spark/distributed backend

But this is a future implementation decision.

Do not prematurely build Spark infrastructure while the linkage
logic is still being validated.

---

# 16. Zingg Benchmark

Zingg may be implemented as a separate experimental pipeline.

Do NOT mix Splink and Zingg internally.

Example:

experiments/
    splink/
    zingg/

Both should receive comparable evaluation data.

Compare independently.

---

# 17. Evaluation Architecture

Evaluation should separate:

### Blocking evaluation

Did we generate candidate pairs containing true matches?

### Linkage evaluation

Did the model correctly score candidate pairs?

### Decision evaluation

Did thresholds produce acceptable MATCH/REVIEW/NON-MATCH outcomes?

### Entity evaluation

Did records belonging to the same real entity end up in the same
entity?

Do not collapse all four into one metric.

---

# 18. Important Design Constraint

Do not optimize for the 50k dataset only.

A design that works on 50k but becomes computationally unreasonable
at 5 million records is not automatically acceptable.

However, do not prematurely introduce distributed infrastructure
without evidence that it is required.

Use measurement to determine when scaling architecture is necessary.