# Cactus WHD — MTR Validation Prototype Brief

**For:** Alan (20 hrs this week)
**Prepared by:** Davis / Hudson
**Date:** Feb 25, 2026

---

## Purpose of This Prototype

This is **not** a production build. This is a targeted proof of concept that demonstrates three things to the client:

1. We understand their problem and their documents
2. We can extract accurate data from their real scanned MTR images using AI Foundry models — not toy low-code demos
3. We can validate that extracted data against their CMS spec and produce a clear, auditable result

That's it. We're earning trust and proving competence so we can win the full engagement. Keep the scope tight.

---

## Scope Guardrails

The full CMS-305 spec covers chemical composition, mechanical properties, Charpy impact, hardness testing, heat treatment, macroetch, microstructural analysis, grain size, and a long list of certification report requirements. We are **not** validating all of that in 20 hours.

**In-scope for this prototype (two categories only):**

1. **Chemical Composition** — The spec defines hard min/max ranges for ~20 elements (Aluminum 0.40–0.60, Carbon 0.045 max, Nickel 50.0–55.0, etc.). The MTR reports actual values with test methods. This is the cleanest apples-to-apples comparison and the most visually impressive in a demo because there are a lot of data points to check.

2. **Mechanical Properties (Tensile Test)** — The spec requires Tensile ≥150,000 psi, Yield 120,000–145,000 psi, Elongation ≥20%, Reduction in Area ≥35%. The MTR reports actual results (186.8 KSI, 143.0 KSI, 25.8%, 39.6%). Simple range checks, very demonstrable.

Everything else — Charpy impact, full hardness survey logic, heat treatment window validation, macroetch compliance, microstructural analysis — is **out of scope** for now. We can reference these as "Phase 2 expansion areas" when we present.

---

## The Documents We Have

We were given two document packages. Use these as the test case:

**CMS-305 Rev D** — The spec (the "rule book"). This is Cactus's internal material specification for API 6ACRA Alloy 718 (UNS N07718), 120K NACE. It defines:

- **Chemical composition limits** (page 2): Hard min/max ranges for ~20 elements — Aluminum 0.40–0.60, Carbon 0.045 max, Nickel 50.0–55.0, Chromium 17.0–21.0, Niobium+Tantalum 4.87–5.20, etc.
- **Mechanical property requirements** (page 2): Tensile ≥150,000 psi, Yield 120,000–145,000 psi, Elongation ≥20%, Reduction in Area ≥35% (for ≤10 in cross-section), Rockwell Hardness 32–40 HRC.
- **Charpy impact requirements** (page 2): At -75°F or below. Multiple thresholds by QTC thickness and orientation.
- **Heat treatment parameters** (page 4): Solution anneal 1870–1925°F, Age hardening 1425–1475°F.
- **Hardness testing rules** (pages 8–9): Individual readings, averages, conversion tables.

**TRP503801 THRU 8 — Premium Alloys MTR Package** (19 pages): This is the real supplier submission. It contains:

- A packing list referencing PO# TRP0050380, CMS-305 Rev D, for 11" OD 718 alloy bar
- A Certificate of Conformity from Premium Alloys
- A Certified Materials Test Report from Huntington Alloys Corporation (Special Metals) — Cert #148754-00 — this is the meat of it. It includes:
  - Chemical analysis with element percentages and test methods (page 3 of the MTR)
  - Tensile test results: 186.8 KSI tensile, 143.0 KSI yield, 39.6% RA, 25.8% elongation (page 4)
  - Hardness survey data at multiple positions (pages 4–5)
  - Heat treatment records (page 5)
  - Charpy impact results (pages 6–9, image-only)
- An Ultrasonic Certification Report from Tejas Testing (page 18)

**Key challenge:** The MTR pages 3–17 are scanned images with no embedded text. This is exactly what Bryan described on the calls — the documents come in as image-based PDFs. The extraction has to work from the images.

---

## Prototype Architecture & Data Flow

The pipeline has three stages. Think of it as: **Ingest → Extract → Validate.**

### Stage 1: Spec Ingestion

Turn the CMS-305 into structured, machine-readable data. For the prototype, this can be a pre-built JSON that represents the in-scope requirements — chemical composition limits and mechanical property thresholds. In production, this would be LLM-extracted and stored per spec version, but for now just get the structure right so the validation engine has something clean to compare against.

Target schema shape:

```json
{
  "spec_id": "CMS-305",
  "revision": "D",
  "material": "Alloy 718 (UNS N07718), 120K NACE",
  "chemical_composition": {
    "Aluminum": {"min": 0.40, "max": 0.60},
    "Carbon": {"min": null, "max": 0.045},
    "Nickel": {"min": 50.0, "max": 55.0}
  },
  "mechanical_properties": {
    "tensile_strength_psi": {"min": 150000},
    "yield_strength_psi": {"min": 120000, "max": 145000},
    "elongation_pct": {"min": 20},
    "reduction_in_area_pct": {"min": 35}
  }
}
```

### Stage 2: MTR Extraction (the money step)

This is what we're really proving. The MTR pages are scanned images — no selectable text, no embedded data.

**Use AI Foundry models with vision capabilities to extract directly from the page images.** Send each relevant MTR page image to the model with a crafted extraction prompt that tells it exactly what to pull and what schema to return. Do NOT fall back to traditional OCR tooling (Tesseract, etc.) — Davis told the client we've moved past that, and we need to demonstrate it.

For the chemical analysis page, the model should return structured data like:

```json
{
  "chemical_analysis": {
    "Carbon": {"value": 0.014, "method": "C/S"},
    "Manganese": {"value": 0.08, "method": "XRF"},
    "Iron": {"value": 18.2, "method": "XRF"},
    "Nickel": {"value": 53.3, "method": "XRF"},
    "Aluminum": {"value": 0.55, "method": "XRF"}
  },
  "tensile_test": {
    "tensile_ksi": 186.8,
    "yield_ksi": 143.0,
    "elongation_pct": 25.8,
    "reduction_of_area_pct": 39.6,
    "orientation": "LONG"
  }
}
```

**Double-extraction pattern (critical for accuracy):** Extract each page twice with slightly different prompts, then compare outputs programmatically. Flag any discrepancies before proceeding. This is the approach Davis described to Ahmed as the "delta check" — extract, re-extract, diff, then validate. It massively reduces hallucination risk, and hallucination management was one of Ahmed's top concerns.

### Stage 3: Validation & Report

Once both sides are structured JSON, the validation is straightforward range comparisons against the in-scope requirements. Produce a clean validation report:

```
VALIDATION REPORT — CMS-305 Rev D vs MTR Cert #148754-00
===========================================================

CHEMICAL COMPOSITION
  Carbon:      0.014  (max 0.045)     ✅ PASS
  Aluminum:    0.55   (0.40–0.60)     ✅ PASS
  Nickel:      53.3   (50.0–55.0)     ✅ PASS
  Chromium:    18.4   (17.0–21.0)     ✅ PASS
  Molybdenum:  2.89   (2.80–3.30)     ✅ PASS
  Titanium:    1.04   (0.80–1.15)     ✅ PASS
  Nb+Ta:       5.17   (4.87–5.20)     ✅ PASS
  Sulfur:      0.0005 (max 0.010)     ✅ PASS
  Manganese:   0.08   (max 0.35)      ✅ PASS
  Phosphorous: 0.005  (max 0.010)     ✅ PASS
  Cobalt:      0.12   (max 1.00)      ✅ PASS
  Silicon:     —      (max 0.35)      ⚠️ NOT REPORTED
  ...

MECHANICAL PROPERTIES
  Tensile:      186,800 psi  (min 150,000)      ✅ PASS
  Yield:        143,000 psi  (120,000–145,000)  ✅ PASS
  Elongation:   25.8%        (min 20%)           ✅ PASS
  Red. of Area: 39.6%        (min 35%)           ✅ PASS

CONFIDENCE
  Extraction agreement (pass 1 vs pass 2): 100% match on in-scope fields

OVERALL: ✅ ALL IN-SCOPE CHECKS PASSED
  Note: Charpy, hardness survey, heat treatment, and other requirements
  are out of scope for this prototype — flagged for Phase 2.
```

---

## Technology & Tooling Guidance

**The AI Foundry models are the star of this prototype.** The extraction and intelligence has to run through Azure AI Foundry — this is what Ahmed got excited about and this is what differentiates us from the Copilot Studio demo they already tried internally (and were disappointed by).

Use Foundry-deployed models with vision capabilities for the image extraction. GPT-4o and Claude Opus are the two strongest options for reading scanned documents right now — use whatever's available in our Foundry instance or deploy one.

Power Platform tooling (Power Automate, Logic Apps, etc.) is fine for backend orchestration, file handling, or gluing pieces together if it saves time — but it should stay in the plumbing. The client-facing demo and the extraction/validation intelligence must clearly be running through AI Foundry. Ahmed doesn't need to see a Power Automate flow; he needs to see that our models are reading their scanned documents and producing structured, accurate results.

For the prototype front-end: a simple UI where someone can upload an MTR, trigger the validation, and see the report is the ideal demo experience. Keep it functional, not flashy. How you build that is up to you — whatever gets us there fastest.

---

## Time Budget (20 hours)

| Task | Hours |
|---|---|
| Review documents, build structured spec JSON for in-scope requirements | 2 |
| Build image extraction pipeline through AI Foundry (PDF → images → model → JSON) | 7 |
| Implement double-extraction & diff for accuracy validation | 3 |
| Build validation logic (spec vs MTR comparison) and report output | 3 |
| End-to-end testing on the Premium Alloys MTR package | 2 |
| Simple demo UI and cleanup | 3 |

---

## What "Done" Looks Like

At the end of 20 hours, we should be able to:

1. Point the system at the Premium Alloys MTR package (real scanned images)
2. Have AI Foundry models extract chemical composition and tensile data from those images
3. Show the double-extraction confidence check (two passes, programmatic diff)
4. Compare every in-scope extracted value against CMS-305 requirements
5. Produce the clean validation report with pass/fail for each data point
6. Walk through this in a simple demo UI

When we present to the client, the narrative is: "We took your actual documents, ran them through our AI Foundry pipeline, extracted accurate structured data from your scanned images, and validated them against your spec. Here's the report. Now imagine this at scale across all your CMS specs, all your suppliers, triggered automatically when MTRs hit your inbox — that's the full solution we'd build."

The out-of-scope items (Charpy, hardness survey logic, heat treatment windows, macroetch/microstructural compliance, the full workflow automation with portal intake and NCR triggering) become the roadmap for the SOW.
