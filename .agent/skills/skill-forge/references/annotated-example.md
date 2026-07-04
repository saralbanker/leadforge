# Annotated Example: sql-query-optimizer

> **Purpose**: This is a reference file showing a 10/10 quality SKILL.md.
> Read this during Phase 2 of skill creation when quality is uncertain.
> Every section includes annotations explaining what makes it good.

---

```yaml
---
name: sql-query-optimizer                    # kebab-case, 3 words — clear domain
description: >
  Use this skill when optimizing SQL queries for performance. Triggers on
  slow query analysis, missing index detection, and execution plan review.
                                             # ≤ 200 chars ✓ | Starts with "Use this skill when" ✓
                                             # Contains 3 concrete trigger scenarios ✓
version: 1.0.0
triggers:                                    # 6 phrases — mix of explicit + implicit
  - "optimize this query"                    # explicit request
  - "query is slow"                          # implicit signal (user describes problem)
  - "add an index"                           # action-oriented
  - "explain plan shows full table scan"     # technical signal
  - "N+1 query problem"                      # pattern name
  - "database performance issue"             # broad but valid
token_budget: 4000                           # Domain specialist = 3000-5000 range
tools_required: ["bash", "read_file", "write_file"]
output_contract:
  format: "Optimized query + before/after EXPLAIN output + index recommendations"
  includes:
    - "Rewritten SQL with comments explaining each change"
    - "EXPLAIN ANALYZE comparison (before vs after)"
    - "Index creation statements if applicable"
    - "Performance improvement estimate"
works_with: ["database-design", "performance-optimizer"]
risk: medium                                 # medium — queries can affect prod data
---
```

> **GOOD**: Every field has a real value. Description is punchy and scannable.
> Triggers use actual user language. `works_with` declares composability.

---

## Mission

> **GOOD**: States the gap ("developers guess at optimization") and the value
> ("evidence-based, measurable improvements"). One paragraph, no fluff.

Eliminate guesswork from SQL query optimization. Most developers add indexes randomly
or rewrite queries by intuition. This skill applies systematic analysis: read the
execution plan, identify the bottleneck operator, apply the correct optimization
pattern, and verify the improvement with measurable before/after metrics.

---

## Core Concepts — BAD vs GOOD

### ❌ BAD Core Concepts (Score: 2/10 — Generic)

> "Consider adding indexes to frequently queried columns. Use EXPLAIN to understand
> query performance. Avoid SELECT * in production queries."

**Why bad**: Anyone could write this. No decision tables, no thresholds, no taxonomies.

### ✅ GOOD Core Concepts (Score: 9/10 — Actionable)

**Bottleneck Operator Classification:**

| EXPLAIN Operator | Severity | Fix Pattern |
|-----------------|----------|-------------|
| Seq Scan on table > 10K rows | HIGH | Add B-tree index on filter columns |
| Nested Loop with inner Seq Scan | CRITICAL | Add index on join column or rewrite as hash join |
| Sort with `external merge` | MEDIUM | Add index matching ORDER BY or increase work_mem |
| Hash Join with batches > 1 | LOW | Increase work_mem (temporary) or denormalize |

> **Why good**: Concrete operators, severity levels, and specific fix patterns.
> A practitioner can look up their EXPLAIN output and find the answer immediately.

---

## Execution Steps — BAD vs GOOD

### ❌ BAD (Score: 2/10)

1. Look at the query
2. Think about what might be slow
3. Try to optimize it

### ✅ GOOD (Score: 9/10)

1. **Capture the baseline** — run `EXPLAIN (ANALYZE, BUFFERS) <query>` and save output
2. **Identify the bottleneck** — find the node with highest `actual time` or `rows removed by filter`
3. **Classify the operator** — match against the Bottleneck Operator table in Core Concepts
4. **Apply the fix pattern** — execute the recommended change (index, rewrite, or config)
5. **Measure the improvement** — run EXPLAIN ANALYZE again, compare `actual time` values
6. **Verify no regression** — run 3 other frequent queries to ensure the change didn't slow them down

> **Why good**: Each step = one concrete action. Imperative verbs. References Core Concepts.
> Step 6 catches a real failure mode (index helps one query, hurts another).

---

## Validation Gate (excerpt)

- [ ] Execution plan captured before AND after optimization
- [ ] Bottleneck operator identified and classified using the severity table
- [ ] At least one measurable metric improved (time, rows scanned, or buffer hits)
- [ ] No regression detected on related queries
- [ ] Index creation includes `CONCURRENTLY` flag for production databases
- [ ] `.skill_usage.json` updated with activation timestamp

> **Why good**: Each checkbox is independently verifiable. Includes the production
> safety check (`CONCURRENTLY`) that beginners forget. 6 shown here — full skill has 12+.

---

## Key Takeaways

1. **Core Concepts** is the hardest section — it must contain **lookup tables**, not advice
2. **Execution Steps** must map to **tool calls**, not thoughts
3. **Triggers** must use **user language**, not textbook terms
4. **Validation Gate** catches **real mistakes**, not style preferences
5. **Description** is a **routing signal** — optimize for fast scanning, not completeness
