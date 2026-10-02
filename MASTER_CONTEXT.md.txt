# MASTER_CONTEXT.md
# CRM Entity Resolution / Deduplication System

## 1. Project Context

Project ini bertujuan membangun sistem Entity Resolution / Deduplication
yang nantinya dapat digunakan untuk kebutuhan data client/perusahaan.

Tujuan akhirnya bukan sekadar membuat demo dari dataset 50.000 record.

Dataset 50.000 record yang saat ini digunakan adalah dataset development
untuk mempelajari, menguji, mengevaluasi, dan mengembangkan sistem sebelum
nantinya digunakan pada data client yang volume, struktur, kualitas, dan
karakteristiknya belum diketahui.

Karena itu, seluruh desain sistem harus mempertimbangkan kemungkinan:

- data jauh lebih besar dari 50.000 record;
- data baru masuk secara berkala;
- format/schema antar sumber dapat berbeda;
- kualitas data dapat berubah;
- missing value dapat muncul;
- typo dan variasi penulisan dapat berubah;
- pola duplikasi dapat berubah;
- model/configuration perlu dapat dievaluasi dan diperbarui;
- sistem perlu mempertahankan history dan entity identity.

Local development dan demo bukan tujuan akhir sistem.
Local environment saat ini hanya merupakan environment development.

---

# 2. Current Development Dataset

Dataset development saat ini:

Customer 360:

`crm_50000_customers_dirty_v3.csv`

Source:

Kaggle Customer 360.

Dataset ini digunakan sebagai dataset eksperimen/development,
bukan sebagai asumsi bentuk data production client.

Schema awal dataset yang diketahui:

- customer_id
- first_name
- last_name
- email
- phone_number
- gender
- dob
- signup_date
- address
- city
- state
- country
- device_id(s)
- source

Namun schema tersebut TIDAK BOLEH dianggap selalu benar.

AI agent harus memeriksa file dataset aktual sebelum menulis kode
yang bergantung pada nama kolom.

---

# 3. Important Identity Concept

Jangan menyamakan:

- record
- customer
- entity

Ketiganya berbeda.

## record_id

`record_id` adalah identifier internal untuk setiap physical record.

Satu record = satu baris data.

`record_id` harus unik dalam dataset yang sedang diproses.

Jika input tidak mempunyai record_id, pipeline harus dapat membuatnya.

`record_id` bukan identitas customer.

---

## customer_id

`customer_id` adalah identifier yang berasal dari source system.

Jangan menganggap customer_id selalu unik atau selalu benar.

Pada dataset development saat ini terdapat sekitar 50.000 record,
tetapi customer_id tidak semuanya unique.

Karena itu customer_id tidak boleh otomatis dianggap sebagai
ground truth entity identity tanpa validasi.

---

## entity_id

`entity_id` adalah identifier entity hasil proses Entity Resolution.

Contoh:

Record A
Record B
Record C

dapat menjadi:

entity_id = ENT-000123

Entity ID harus dipisahkan dari source customer_id.

---

# 4. Core Technology Direction

Current primary linkage engine:

**Splink**

Current execution environment:

- Python
- Splink
- DuckDB
- VS Code
- local CPU development

Namun local execution bukan batas arsitektur.

System harus dirancang agar business/linkage logic tidak terlalu
terikat pada local DuckDB implementation.

Future scale dapat menggunakan backend/distributed execution apabila
volume production membutuhkannya.

Jangan mengasumsikan bahwa migrasi DuckDB → Spark hanya berarti
mengganti satu library.

Pisahkan:

- business/linkage logic
- execution/backend logic

sebisa mungkin.

---

# 5. Zingg

Zingg adalah alternatif/challenger yang perlu dipahami dan dapat
digunakan sebagai benchmark terhadap Splink.

Jangan menganggap:

"Splink pasti lebih baik daripada Zingg."

Dan jangan menganggap:

"Zingg lebih production daripada Splink."

Keduanya harus dibandingkan berdasarkan requirement dan evidence.

Perbandingan dapat mencakup:

- accuracy
- precision
- recall
- F1
- false positives
- false negatives
- candidate pairs
- blocking coverage
- runtime
- memory/resource usage
- typo handling
- missing-value handling
- explainability
- human review workflow
- labeling effort
- incremental processing
- model update/retraining
- scalability
- operational complexity

Jangan menggabungkan score Splink dan Zingg secara langsung tanpa
memastikan bahwa score tersebut memang comparable.

---

# 6. Main System Pipeline

Target architecture secara konseptual:

INPUT DATA
    ↓
Schema Validation
    ↓
Record ID Generation
    ↓
Standardization
    ↓
Feature Engineering
    ↓
Blocking / Candidate Generation
    ↓
Entity Resolution / Linkage
    ↓
Decision
    ↓
MATCH / REVIEW / NEW
    ↓
Entity Assignment
    ↓
Master / History Update
    ↓
Monitoring / Feedback
    ↓
Model Evaluation / Retraining when needed


---

# 7. New Data Workflow

Ketika data baru masuk:

1. Validate schema.
2. Generate or preserve record_id.
3. Preserve raw/original values.
4. Standardize fields.
5. Generate linkage-related features.
6. Deduplicate records inside the new batch.
7. Resolve new entities against existing master/entity data.
8. Produce MATCH / REVIEW / NEW decisions.
9. Assign entity_id.
10. Update master/history according to decision policy.
11. Preserve review information and lineage.

New records should not simply be compared blindly against every
historical raw record.

Internal duplicates in the new batch should be resolved first where
appropriate.

---

# 8. Standardization

Standardization is a mandatory preprocessing layer.

Raw data must be preserved.

Do not overwrite raw values simply because standardized values exist.

Examples of possible standardized fields:

- first_name_std
- last_name_std
- email_std
- phone_std
- address_std
- city_std
- state_std
- country_std
- device_ids_std

Possible operations include:

- lowercase
- trim
- whitespace normalization
- punctuation normalization
- phone normalization
- email normalization
- address normalization

However, do not perform aggressive transformations without evidence
that they improve linkage.

Do not silently invent typo correction rules.

---

# 9. Feature Engineering

Feature engineering is part of the Entity Resolution system.

It is not limited to generic machine-learning features.

Features should have a linkage reason.

Examples:

- normalized names
- phone digits / suffix
- email local part/domain
- name length
- name prefix
- address tokens
- device count
- missingness indicators
- blocking keys
- field availability indicators

AI must explain why a new feature is useful before introducing
non-trivial features.

Avoid creating large numbers of features merely because they are easy
to calculate.

---

# 10. Blocking

Blocking is necessary to avoid unnecessary all-pairs comparisons.

The system should NOT rely permanently on one arbitrary blocking rule.

Potential blocking strategies may include combinations such as:

- exact email
- exact phone
- first_name + last_name
- last_name + dob
- first_name + dob
- city + name
- device identifier
- other data-driven keys

These are examples only.

The final blocking strategy must be determined through experiments.

Blocking evaluation should consider:

- candidate pair count
- reference pair coverage
- recall/coverage
- runtime
- memory/resource requirements
- block size distribution

A blocking rule that is fast but misses many true matches is not
automatically good.

A blocking rule with excellent recall but unreasonable candidate
volume is also not automatically good.

Complementary blocking strategies may be necessary.

---

# 11. Splink Matching

Splink is currently the primary linkage engine.

The intended approach is probabilistic record linkage.

The system should make use of field-level comparison evidence.

Example:

first_name
    ↓
exact / fuzzy / different / null

email
    ↓
exact / different / null

phone
    ↓
exact / fuzzy / different

dob
    ↓
exact / different

These comparison results contribute to the overall pair evidence.

The system should retain enough information to understand why a pair
received its score/probability.

---

# 12. Typo Handling

A typo in one field must NOT automatically mean REVIEW.

Example:

Record A:

Jonathan Smith
jonathan@gmail.com
08123456789
1995-01-01

Record B:

Jonatan Smith
jonathan@gmail.com
08123456789
1995-01-01

The first name contains a typo, but the other fields provide strong
evidence.

The decision must be based on combined evidence.

Likewise, if multiple fields conflict, a high similarity on one field
should not automatically create a match.

Do not implement deterministic typo correction as the primary matching
mechanism unless experiments justify it.

Both Splink and Zingg can support fuzzy/similarity-based matching.

The project must not claim that one handles typos better without
benchmark evidence.

---

# 13. Decision Policy

Model score/probability and business decision threshold are different
concepts.

The intended decision policy may use two thresholds:

P < T_LOW
    → NON_MATCH

T_LOW <= P < T_HIGH
    → REVIEW

P >= T_HIGH
    → MATCH

Actual thresholds must be empirically evaluated.

Do not arbitrarily select 0.5, 0.65, or another threshold merely
because it is common.

Evaluate thresholds using available labels and business requirements.

Metrics can include:

- precision
- recall
- F1
- false positive rate
- false negatives
- auto-match rate
- review rate
- non-match rate

---

# 14. Labels

The project may use different levels of labels.

## Silver labels

Automatically constructed from strong identity signals.

Silver labels are useful for development but should not automatically
be treated as absolute ground truth.

## Gold labels

Human-reviewed pair labels.

Gold labels are preferred for:

- evaluation
- threshold tuning
- blocking validation
- error analysis
- model comparison
- future parameter estimation/retraining

Human review should therefore create reusable feedback data.

---

# 15. Model Lifecycle

The model should NOT be retrained every time a new CSV arrives.

Normal workflow:

Model v1
    ↓
New data
    ↓
Inference
    ↓
MATCH / REVIEW / NEW
    ↓
Human review / monitoring
    ↓
Collect useful labels
    ↓
Detect degradation / drift / new patterns
    ↓
Retraining when justified
    ↓
Model v2
    ↓
Offline evaluation
    ↓
Promotion if acceptable

Retraining should be triggered by evidence such as:

- performance degradation
- data drift
- new data sources
- new schema/format patterns
- large accumulation of reviewed cases
- repeated false positives
- repeated false negatives
- significant review volume
- meaningful changes in data quality

Do not retrain simply because a new file arrived.

---

# 16. Model Versioning

Models/configurations should be versioned.

Example:

models/
    v1/
        model.json
        metadata.json
        thresholds.json
        evaluation.json

    v2/
        model.json
        metadata.json
        thresholds.json
        evaluation.json

Never silently overwrite a previously validated production model.

A new version should be evaluated before promotion.

---

# 17. Master Data and History

The final system should distinguish between:

- raw source records
- standardized records
- resolved entities
- master representation
- linkage history
- review decisions

Do not destroy raw values.

The system should preserve lineage so that an entity assignment can
be traced back to source records.

---

# 18. Scalability Requirement

The system must be designed with the assumption that production data
may be much larger than 50k.

Potential future scale:

50k
→ 500k
→ millions
→ potentially tens of millions

The actual production volume is currently unknown.

Therefore:

- avoid unnecessary O(n²) operations;
- benchmark candidate generation;
- keep blocking configurable;
- avoid loading unnecessary data into memory;
- separate business logic from execution backend;
- consider partitioning/distributed execution when justified;
- measure runtime and resource consumption.

Do not claim scalability based only on the 50k development dataset.

---

# 19. Current Development vs Final System

Current:

Python + Splink + DuckDB + VS Code

This is the current development implementation.

It does NOT mean:

"the final system is a local 50k demo."

The final architecture should support:

- larger datasets;
- repeated/incremental data ingestion;
- multiple data sources;
- changing data quality;
- human feedback;
- model/configuration versioning;
- evaluation;
- retraining;
- scalable execution.

---

# 20. Important Engineering Principle

The AI agent should distinguish between:

FACT
    = verified from repository/data/documentation

DECISION
    = current project choice

ASSUMPTION
    = something not yet verified

HYPOTHESIS
    = proposed idea requiring experiment

RECOMMENDATION
    = agent suggestion

These categories must not be mixed.

---

# 21. Current Decisions Are Not Sacred

The architecture above represents the current project direction.

AI agent MUST NOT blindly obey it.

If repository inspection, data profiling, benchmarking, documentation,
or experiments indicate that a decision is technically incorrect,
incomplete, non-scalable, or inconsistent with requirements, the agent
must say so.

For significant conflicts:

1. State the current decision.
2. State the observed evidence.
3. Explain the conflict.
4. Explain the technical consequence.
5. Propose alternatives.
6. Recommend an experiment or decision.
7. Wait for confirmation before making major architectural changes.

Do not silently change major architecture.

---

# 22. No Invented Facts

Never invent:

- column names
- data distributions
- model metrics
- blocking coverage
- runtime
- accuracy
- production volume
- client requirements
- API behavior
- library capabilities

If something is unknown:

say that it is unknown.

Inspect the repository/data/documentation where possible.

---

# 23. Development Philosophy

The objective is not:

"make the notebook run."

The objective is:

"build a technically defensible Entity Resolution system that can
eventually move from development data to real client data."

Therefore every major component should answer:

- Why is it needed?
- What problem does it solve?
- How is it evaluated?
- What happens when data changes?
- What happens when volume grows?
- How is it monitored?
- How can it be replaced or upgraded?