# Odin Dev Pack — Quillhub Autonomous Contract Intelligence Challenge

## The Mission

You are tasked with building an autonomous contract intelligence engine for **Quillhub Inc.**, a B2B SaaS company that provides an enterprise route optimization platform called **Route Optimizer**. 

Quillhub has grown quickly, executing multiple commercial agreements across upstream cloud hosting providers, enterprise retail customers, logistics distribution partners, and specialized contractor agencies. However, these agreements were negotiated independently over time, creating hidden legal contradictions, financial liabilities, operational mismatches, and compliance vulnerabilities.

Your system must ingest this repository, analyze the portfolio holistically, monitor incoming operational events across time checkpoints, and surface critical risks, deadlines, and financial exposures.

**There is no spoon-fed schema or pre-baked answer key.** You and your team must design the architecture, discover the contractual relationships, trace the financial leaks, and prove your system's intelligence from the raw files.

---

## Folder Layout

```
odin_dev_pack/
├── README.md                          ← You are here
├── clock.json                         ← Simulated time clock with 3 checkpoint dates
├── docs/
│   └── format_spec.md                 ← Input specifications, drop model, and citation rules
└── bundle/
    ├── manifest.json                  ← File list and titles (no relationships revealed)
    ├── company/
    │   └── context.txt                ← Quillhub business profile, addresses, corporate facts
    ├── contracts/
    │   ├── STD.txt & STD.pdf          # Master Standard Terms (incorporated by reference)
    │   ├── A1.txt & A1.pdf            # Upstream Cloud Hosting Agreement
    │   ├── A2.txt & A2.pdf            # Upstream Service Level Agreement (SLA)
    │   ├── A3.txt & A3.pdf            # SLA Amendment No. 1
    │   ├── B1.txt & B1.pdf            # Enterprise Retail Customer Agreement
    │   ├── B2.txt & B2.pdf            # Data Processing & Security Addendum
    │   ├── C1.txt & C1.pdf            # Logistics Customer Agreement
    │   └── D1.txt & D1.pdf            # Independent Contractor Agreement
    ├── data/
    │   ├── payments_ledger.csv        # Historical transaction payments & invoices
    │   └── holidays.csv               # Observed business holidays
    └── events/
        ├── events_drop1.jsonl         # Operational communications & incidents (Drop 1)
        └── events_drop2.jsonl         # Operational communications & incidents (Drop 2)
```

---

## What Your System Must Uncover

A successful system must autonomously solve key challenges across the portfolio:

1. **Cross-Contract Contradictions & Territorial Conflicts**
2. **Upstream vs. Downstream Financial Recovery Gaps**
3. **Silent Amendment Supersession**
4. **Hidden External Defaults & Lapsed Policies**
5. **Timeline & Obligation Tracking**
6. **Event Monitoring & Action Drafting**
7. **Data Hygiene & Resilience**

---

## Attribution

The Standard Terms in `STD.txt` are adapted from the Common Paper Cloud Service Agreement Standard Terms Version 2.0 under CC BY 4.0. Modifications were made to section numbering, defined terms, and provisions to fit this scenario. Original: https://commonpaper.com/standards/cloud-service-agreement/2.0/

*This dataset is entirely fictional. All companies, individuals, financial amounts, and contract terms are simulated for testing.*
