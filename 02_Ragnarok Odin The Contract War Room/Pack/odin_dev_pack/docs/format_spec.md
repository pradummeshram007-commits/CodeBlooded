# Input & Dataset Format Specification

## Overview

The dataset is organized as a **bundle** — a structured directory containing commercial contracts, corporate context, payment ledgers, holiday schedules, and event feeds representing Quillhub's operating environment over time.

---

## Bundle Structure

```
bundle/
  manifest.json
  company/context.txt
  contracts/<id>.txt
  contracts/<id>.pdf
  data/payments_ledger.csv
  data/holidays.csv
  events/events_drop1.jsonl
  events/events_drop2.jsonl
clock.json
```

---

## File Conventions

### 1. Contracts (`contracts/*.txt` and `contracts/*.pdf`)
- Each agreement is provided as a plain UTF-8 text file (`.txt`) with an identical twin document (`.pdf`).
- **The `.txt` file is the canonical anchor for all citations and exact quote matching.**
- Agreements follow standard B2B SaaS structures (Cover Page + incorporated Standard Terms `STD.txt`).

### 2. Company Context (`company/context.txt`)
- Plain text outlining Quillhub Inc.'s corporate background, key personnel, official notice addresses, and corporate insurance policies.

### 3. Manifest (`manifest.json`)
- A flat inventory listing every file in the bundle with its human-readable title.

### 4. Payments Ledger (`data/payments_ledger.csv`)
- Accounting ledger tracking historical receivables and payables.

### 5. Observed Holidays (`data/holidays.csv`)
- Schedule of observed business holidays.

### 6. Events Feed (`events/*.jsonl`)
- Real-time operational communications, incident notifications, deliverable handoffs, and customer emails.

*Note: Real-world events contain operational noise that requires no contractual action, as well as critical incidents that trigger strict liability windows.*

### 7. Simulated Clock (`clock.json`)
- Defines the temporal progression of the challenge:

- Your analysis engine should evaluate obligations, deadlines, and exposures as of each checkpoint date.

---

## Citation & Verification Standard

Any risk, claim, or obligation surfaced by your system must be verifiable against the source documents. Citations must contain:
1. **Document ID**: The filename without extension (e.g. `"A1"`, `"B1"`, `"STD"`).
2. **Clause Reference**: The section number or heading as written in the contract (e.g. `"§3.1"`, `"Section 4.3"`, `"Special Terms §1"`).
3. **Verbatim Quote**: An exact substring from the `.txt` file supporting the finding. Quotes must be findable via simple text search.

---

## Two-Drop Model

Events are delivered in two staged drops:
* **Drop 1 (`events_drop1.jsonl`)**: Initial portfolio analysis covering events E-01 through E-10.
* **Drop 2 (`events_drop2.jsonl`)**: Mid-cycle updates covering events E-11 through E-18, introducing new incidents, milestones, and status changes.

Systems must be capable of updating their evaluations dynamically as new event drops and clock checkpoints arrive.

---

## Grounded Reasoning Requirements

Your system's explanations must be rigorously grounded in the provided files:
* **Who did what**: The factual action or incident from the event logs or contract execution.
* **Why it matters**: The specific contract clause, SLA threshold, or legal condition that applies.
* **Legal / Financial Consequence**: The concrete outcome (e.g., who pays whom, breach status, or unrecoverable financial gap).

Systems will be evaluated on their ability to uncover genuine contractual truths without hallucinating unverified assumptions.
