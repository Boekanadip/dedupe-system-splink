---
name: blocking-benchmark
description: Benchmark multiple Splink blocking rules for candidate count, coverage on reviewed pairs, skew, and runtime before prediction.
---

## Procedure
1. Start with strict equi-join rules.
2. Measure each rule independently.
3. Measure the cumulative union after deduplication.
4. Inspect largest blocks/skew.
5. Where reviewed positive pairs exist, calculate how many positives each rule and the union retain.
6. Reject rules that create disproportionate candidate counts without meaningful coverage.
7. Save a table of rule, candidate count, runtime, coverage and notes.

## Decision policy
The final rule list should contain multiple complementary strict rules rather than one overly broad rule. Do not claim an optimal rule set without measurements.
