# Cactus WHD — Developer & SOP Guide

> **Generated:** 2026-03-02  
> **Scope:** MTR Intake SOP · CMS Spec Validation · Approved Provider Correlation · Azure Functions HTTP API  
> **Function App:** `function_app.py` · **Blob Module:** `blob_storage.py` · **Container:** `cactus-whd`

---

## Table of Contents

- [1. Business Context](#1-business-context)
- [2. MTR Intake Workflow (SOP)](#2-mtr-intake-workflow-sop)
  - [2.1 Intake Baseline](#21-intake-baseline)
  - [2.2 Gate Model](#22-gate-model)
  - [2.3 Queue Ownership](#23-queue-ownership)
  - [2.4 File Format Handling](#24-file-format-handling)
  - [2.5 Disposition Outcomes](#25-disposition-outcomes)
  - [2.6 Supplier Performance Loop](#26-supplier-performance-loop)
- [3. CMS Spec Validation Framework](#3-cms-spec-validation-framework)
  - [3.1 CMS Resolution Logic](#31-cms-resolution-logic)
  - [3.2 CMS-to-Provider Crosswalk](#32-cms-to-provider-crosswalk)
  - [3.3 CMS Spec Reference Cards](#33-cms-spec-reference-cards)
- [4. Approved Provider Rules](#4-approved-provider-rules)
  - [4.1 Match Requirements](#41-match-requirements)
  - [4.2 Risk Flags](#42-risk-flags)
  - [4.3 Single-Source Risks](#43-single-source-risks)
  - [4.4 SOP Enforcement Rules](#44-sop-enforcement-rules)
- [5. Azure Functions HTTP API](#5-azure-functions-http-api)
  - [5.1 Overview](#51-overview)
  - [5.2 Route: GET /api/cms/providers](#52-route-get-apicmsproviders)
  - [5.3 Route: GET /api/cms/crosswalk](#53-route-get-apicmscrosswalk)
  - [5.4 Route: GET /api/cms/chunks](#54-route-get-apicmschunks)
  - [5.5 Cross-Route Validation Pattern](#55-cross-route-validation-pattern)
  - [5.6 Error Handling Reference](#56-error-handling-reference)
- [6. Local Development Setup](#6-local-development-setup)
  - [6.1 Azurite Troubleshooting](#61-azurite-troubleshooting)
- [7. JSON Artifact Reference](#7-json-artifact-reference)

---

## 1. Business Context

**Cactus Wellhead (Cactus, Inc. / NYSE: WHD)** manufactures and services surface pressure control equipment across the full well lifecycle — drilling, completion/fracking, and production.

### Core Product Buckets

| Bucket | Products |
|---|---|
| **Wellhead Systems** | SafeDrill® line, API 6A wellhead assemblies |
| **Frac Equipment** | Frac stacks, zipper manifolds |
| **Production** | Production trees, surface equipment |
| **Field Services** | Installs, swaps, maintenance, frac operations |

### Strategic Context (2026)

> Cactus acquired **65%** of Baker Hughes' surface pressure control business (effective **January 1, 2026**), forming **Cactus International** — significantly expanding international footprint in NOC/IOC aftermarkets.

### The "Big Five" Material CTQs

Every pressure-bearing material is governed by five critical-to-quality characteristics:

| # | CTQ | What is Controlled |
|---|---|---|
| 1 | **Chemistry** | Element-by-element vs. CMS min/max table |
| 2 | **Mechanical Properties** | Yield, tensile, elongation, reduction in area |
| 3 | **Charpy Impact (CVN)** | Temperature, orientation, specimen size, average/individual acceptance |
| 4 | **Heat Treatment** | Austenitize temp, quench media, temper temp, soak time |
| 5 | **Hardness** | Scale, location, frequency, NACE caps (sour-service) |

---

## 2. MTR Intake Workflow (SOP)

Cactus receives MTR packets from two classes of counterparties:

- **Type A** — Customers submitting MTRs for incoming customer-supplied material
- **Type B** — Suppliers shipping material with an MTR/CoC packet

> **Rule:** The intake workflow is unified across both source types, then risk-branched at Gate 1.

---

### 2.1 Intake Baseline

**Step 1 — Packet Receipt and Case Creation**

Create an `MTR Validation Case` record with:

```
counterparty  ·  PO/line  ·  part  ·  heat/lot  ·  spec/grade  ·  material form
```

Then:
1. Ingest all attachments (see [File Format Handling](#24-file-format-handling))
2. Malware scan + SHA-256 hash all originals before processing
3. Archive originals immutably
4. Normalize: OCR scanned PDFs, deskew images, extract tables

---

### 2.2 Gate Model

```
INTAKE → [Gate 0] → [Gate 1] → [Gate 2/3] → [Gate 4]
          Completeness  Traceability  Technical    Record Lock
```

| Gate | Name | Owner | Pass Criteria |
|---|---|---|---|
| **Gate 0** | Packet Completeness | Intake / Doc Control | All minimum required fields present |
| **Gate 1** | Identity & Traceability | Receiving QC | Heat number matches PO + physical tag; grade matches PO |
| **Gate 2/3** | Technical Validation | QE / Metallurgy | All CTQs pass CMS limits; provider approved |
| **Gate 4** | Record Lock | Records Control | Case linked to CMS rev + provider IDs + disposition |

**Gate 0 — Minimum Required Fields**

- [ ] Heat / cast number
- [ ] PO number and line item
- [ ] Part or material identifier
- [ ] Governing spec/grade + revision
- [ ] Chemistry table (per applicable CMS)
- [ ] Mechanical properties (YS, UTS, elongation, RA)
- [ ] Charpy results *(when required by PO/EPS)*
- [ ] Heat treatment actuals *(when required)*
- [ ] Hardness results — method, location, values
- [ ] NDT certificate reference *(when applicable)*
- [ ] Test lab or provider identification

> If any required field is missing: return as **Incomplete Packet** with a specific punch list. Do not begin technical validation.

**Gate 1 — Common Rejection Reasons**

- Heat number mismatch or cross-reference without certification
- Wrong grade (e.g., AISI 4130 submitted when 4140 required)
- Multiple heats aggregated without individual certs per heat

---

### 2.3 Queue Ownership

| Queue | Responsible Party | Function |
|---|---|---|
| Intake / Doc Control | Receiving Admin / QMS | Packet completeness (Gate 0) |
| Receiving QC | Inspector / QC Tech | Identity + traceability (Gate 1) |
| QE / Metallurgy | Quality Engineer | Technical validation (Gates 2/3) |
| Quality Manager | QE or QM | Deviation disposition |
| Records Control | Doc Control | Final lock + archive (Gate 4) |

---

### 2.4 File Format Handling

<details>
<summary><strong>PDF Types</strong></summary>

| Type | Description | Processing |
|---|---|---|
| Text-based | From ERP/QMS — fully searchable | Direct field extraction |
| Scanned | Image-only | OCR required |
| Hybrid | Text layer with OCR artifacts | OCR + alignment correction |
| Portfolio | Multiple certs in one container | Unpack, process individually |

</details>

<details>
<summary><strong>Office Documents</strong></summary>

| Type | Notes |
|---|---|
| DOCX | Certificate templates with typed values + signature blocks |
| XLSX | Chemistry + tensile + impact tables (high value if true tables) |
| Issues | Merged cells, hidden rows, macros, printed-to-PDF derivatives |

</details>

<details>
<summary><strong>Images</strong></summary>

Formats: `JPG` · `PNG` · `TIFF` · `HEIC`  
Common issues: perspective distortion, glare, low DPI, missing corners

</details>

<details>
<summary><strong>Package Formats</strong></summary>

- `ZIP` bundles of full MTR packets
- `MSG` / `EML` email attachments (intact or forwarded chains)

</details>

> All formats must route through a **normalize → validate** pipeline before any automated field extraction or CMS-gated validation is applied.

---

### 2.5 Disposition Outcomes

| Outcome | Meaning |
|---|---|
| ✅ **ACCEPTED** | All gates pass; records locked to validated case |
| ⚠️ **ACCEPTED WITH CONDITIONS** | Minor open items with defined resolution path |
| ❌ **REJECTED** | Material fails spec limits or traceability cannot be established |
| 🔄 **DEVIATION REQUIRED** | Out-of-spec but potentially acceptable via SDR/waiver |

> **Rule:** No silent substitutions. Any change after PO placement requires a formal **SDR (Supplier Deviation Request)** or EPS waiver with Quality signature.

---

### 2.6 Supplier Performance Loop

Track continuously per supplier **and** per supplier site:

- First-pass acceptance rate (by spec / material family)
- Top failure causes (Charpy gap, heat number mismatch, hardness method, etc.)
- Average queue turnaround time by gate
- Repeat non-conformances by supplier/site/template
- SDR/waiver frequency and cycle time

> Feed results back into supplier qualification and risk scoring.

---

## 3. CMS Spec Validation Framework

### 3.1 CMS Resolution Logic

For every MTR validation case, resolve the applicable CMS set from PO + material/part mapping:

```
4140 forgings    →  CMS-002 + CMS-107  (+ CMS-004 if Charpy required)
Alloy 718        →  CMS-002 + CMS-305  (+ CMS-004 for Charpy)
17-4PH NACE      →  CMS-002 + CMS-303
Coating on part  →  COATING_PLATING    (when PO specifies)
```

> **Rule:** CMS-002 is always the floor. CMS-004 is applied whenever Charpy is required. Material-specific CMS layers on top. Conflicts resolve to CMS-002.

---

### 3.2 CMS-to-Provider Crosswalk

| CMS Spec | Mandatory Process Codes | Conditional Codes | Trigger |
|---|---|---|---|
| **CMS-002** | `LAB-001` `CHT-GEN` | `CNT-002` `CNT-003` `CNT-004` `CNT-005` `CNT-007` | NDT per PO/EPS |
| **CMS-004** | `LAB-001` | — | Applied when Charpy required |
| **CMS-107** | `LAB-001` `CHT-GEN` | `CNT-005` + additional `CNT-*` | Per flowdown |
| **CMS-118** | `LAB-001` `CHT-GEN` | `CNT-005` + additional `CNT-*` | Per flowdown |
| **CMS-303** | `LAB-001` `CHT-GEN` | `CNT-002` `CNT-003` `CNT-004` `CNT-005` `CNT-007` | Per PO/EPS |
| **CMS-305** | `LAB-001` `CHT-GEN` | `CNT-005` + additional `CNT-*` | Per spec |
| **COATING_PLATING** | `CCS-608` `CCS-609` `CCS-610` `CCS-612` `CST-800` `CST-801` `CST-811` | — | PO specifies coating |

---

### 3.3 CMS Spec Reference Cards

<details>
<summary><strong>CMS-002 — Base Requirements (Forgings & Wrought Products)</strong></summary>

**Scope:** Foundational requirements for all forgings, tubulars, bars, and mill shapes. Always active.

**Key References:** API 6A · ASTM A370 · ASTM A751 · ASTM E10 · ASTM E18 · ASTM E92 · SAE AMS2750F

**Required MTR Evidence:**
- Chemistry · Tensile/mechanicals · Charpy (if required) · Hardness · Heat treat actuals · Heat/lot-to-PO traceability

**SOP Notes:**
- CMS-002 takes precedence over any conflicting requirement in a material-specific CMS
- CMS-002-1 applies to API 6A PSL-3 75K yield strength bodies >1,000 lbs during heat treating
- QTC must experience same heat treatment processing as production parts
- China forgings: minimum 5:1 reduction ratio; 4" spacing in oven; thermocouple on center production part

</details>

<details>
<summary><strong>CMS-004 — Charpy / CVN Impact Framework</strong></summary>

**Scope:** Charpy test parameters, sub-size correlation rules, and acceptance logic.

**Sub-size Adjustment Factors:**

| Specimen | Adjustment Factor |
|---|---|
| 10mm × 7.5mm | 0.833 |
| 10mm × 5.0mm | 0.667 |
| 10mm × 2.5mm | 0.333 |

**SOP Notes:**
- Do not assume LAB-001 tensile approval covers Charpy — verify CVN scope explicitly
- China forgings: three Charpy sets required per heat lot at EPS temp, 0°F, and midpoint

</details>

<details>
<summary><strong>CMS-107 — 4140 Low-Alloy Steel</strong></summary>

**Scope:** AISI 4140 class — most common material family in pressure-control forgings. Tight chemistry and HT window controls.

**Required MTR Evidence:**
- Chemistry vs. CMS-107 element tables
- Q&T route actuals (austenitize/quench/temper temps, soak, quench media)
- Tensile + impact + hardness results
- HT furnace record reference

**SOP Notes:**
- Validate element-by-element including residuals
- Hardness caps apply — validate NACE tables for sour-service flowdowns

</details>

<details>
<summary><strong>CMS-118 — 4340 Low-Alloy Steel</strong></summary>

**Scope:** AISI 4340 class — higher hardenability than 4140; more sensitive to section size and quench media.

**SOP Notes:**
- Quench media and section size controls are critical
- HT supplier approval must be at **site level** — company-level approval alone is insufficient

</details>

<details>
<summary><strong>CMS-303 — 17-4PH NACE Route</strong></summary>

**Scope:** UNS S17400 — corrosion-resistant and NACE-compliant aging condition routes.

**Required MTR Evidence:**
- Full chemistry including Cu and Nb/Cb
- Ferrite / microstructure evaluation (where required)
- Aging condition actuals (H900 / H1025 / H1150-M etc.)
- Hardness (method + limits) · Traceability

**SOP Notes:**
- Validate aging condition on MTR matches PO/EPS requirement exactly
- NACE route: verify hardness cap compliance and modified chemistry limits
- Confirm LAB-001 scope covers microscopy, metallography, and ferrite/delta ferrite evaluation

</details>

<details>
<summary><strong>CMS-305 — Alloy 718 / API 6ACRA / NACE Route</strong></summary>

**Scope:** UNS N07718 — highest-scrutiny spec in the CMS suite per API 6ACRA.

**Required MTR Evidence:**
- Full chemistry: Nb, Mo, Ti, Al trace elements included
- Charpy impact results
- Hardness (method, location, limits)
- Heat treat route: solution anneal + double age temps and soak times
- Macroetch (ASTM A604) + microstructure phase examination
- API 6ACRA traceability artifacts (melt → finished forging)

**SOP Notes:**
- Confirm LAB-001 scope covers: ASTM A604, ASTM E1181, metallography, phase evaluation
- API 6ACRA traceability chain must be **unbroken** from melt source through finished forging
- Verify CHT-GEN and CNT-005 are **not** single-source for this material route

</details>

<details>
<summary><strong>COATING_PLATING — Surface Treatment Requirements</strong></summary>

**Scope:** Coating and plating requirements when specified by PO or EPS.

**Process Codes:**

| Code | Process |
|---|---|
| `CCS-608` | Xylan 1070 |
| `CCS-609` | Xylan 1052 |
| `CCS-610` | Xylan 1014 |
| `CCS-612` | Phosphorous Nickel ⚠️ Single Source |
| `CST-800` | Copper Plating |
| `CST-801` | Salt Bath Nitriding QPQ |
| `CST-811` | *(single-source — risk review required)* |

**SOP Notes:**
- Validate at **site level** — company name alone is insufficient
- If primary supplier outsources coating/plating, the sub-tier must also be on the approved list

</details>

---

## 4. Approved Provider Rules

### 4.1 Match Requirements

A provider match requires **all four fields** to align:

```
supplier_name  +  site address/city  +  process_code  +  approval_status = "Active"
```

> ⚠️ **Company name + process code alone is NOT sufficient.** Site-level approval is mandatory.

---

### 4.2 Risk Flags

| Flag in `notes` field | Required Action |
|---|---|
| `ADDRESS NEEDS MANUAL REVIEW` | Route to **Quality hold** — no auto-accept until address is manually verified |
| `SINGLE SOURCE — risk review required` | Route to **risk review queue** before final acceptance |

---

### 4.3 Single-Source Risks

The following process codes have only one approved provider in the list:

| Process Code | Process | Risk Action |
|---|---|---|
| `CCS-612` | Phosphorous Nickel Plating | Risk review before acceptance |
| `CHT-100` | Gas Carburizing (LST Heat Treating) | Risk review; initiate second-source qualification |
| `CST-811` | Surface Treatment | Risk review before acceptance |
| `CNT-007` | NDT method | Risk review; initiate second-source qualification |

---

### 4.4 SOP Enforcement Rules

| Rule | Requirement |
|---|---|
| **Rule 1** | Provider match required at site level (supplier + address/city + process code + Active status) |
| **Rule 2** | `ADDRESS NEEDS MANUAL REVIEW` → Quality hold, no auto-accept |
| **Rule 3** | `SINGLE SOURCE` → risk review required before final acceptance |
| **Rule 4** | Test method present but provider code missing/mismatched → Conditional / Needs Review |
| **Rule 5** | Accepted cases must lock to: CMS rev + provider IDs + heat/lot + PO line + dispositioner + date |
| **Rule 6** | No silent changes — all post-PO changes require formal SDR or EPS waiver |
| **Rule 7** | CMS-002 always applies; CMS-004 when Charpy required; material CMS layers on top |
| **Rule 8** | Outsourced sub-tier processes must also be on the approved provider list |

---

## 5. Azure Functions HTTP API

### 5.1 Overview

| Property | Value |
|---|---|
| **Base URL (local)** | `http://localhost:7071/api` |
| **Auth Level** | `ANONYMOUS` — no API key required |
| **Methods** | `GET` only |
| **Response format** | `application/json` — array `[]` on success, `{"error":"..."}` on failure |
| **Encoding** | UTF-8 |

**Routes Summary:**

| # | Route | Returns |
|---|---|---|
| 1 | `GET /api/cms/providers` | Full approved-providers list |
| 2 | `GET /api/cms/crosswalk` | CMS-to-process-code crosswalk |
| 3 | `GET /api/cms/chunks?cms_number=` | Filtered JSONL chunks by CMS spec |

---

### 5.2 Route: GET /api/cms/providers

**Returns** the complete approved sub-supplier / provider list from `cms_approved_providers.json`.

One record = one provider × one process code × one physical site.

#### Response Schema

```jsonc
{
  "provider_id":       1,              // integer — unique sequential ID
  "supplier_name":     "Accu-Test Labs",
  "site_address":      "6722 Guhn Road",
  "site_city":         "Houston",
  "site_state":        "TX",
  "site_zip":          "77040",
  "process_code":      "LAB-001",      // e.g. "LAB-001", "CNT-002", "CHT-GEN"
  "process_name":      "Laboratory Metallurgical Testing",
  "process_category":  "Lab",          // "NDT" | "Lab" | "HeatTreat" | "Coating" | "Plating"
  "parent_supplier":   "",             // parent company if delegated
  "approval_status":   "Active",       // "Active" | "Inactive"
  "last_audit_date":   "",
  "notes":             ""              // flags: "ADDRESS NEEDS MANUAL REVIEW", "SINGLE SOURCE..."
}
```

#### Python Example

```python
import requests

BASE_URL = "http://localhost:7071/api"

def get_approved_providers() -> list[dict]:
    resp = requests.get(f"{BASE_URL}/cms/providers", timeout=30)
    resp.raise_for_status()
    return resp.json()

providers = get_approved_providers()
print(f"Total providers: {len(providers)}")

# Filter to active LAB-001 providers
labs = [p for p in providers
        if p["process_code"] == "LAB-001" and p["approval_status"] == "Active"]

# Flag records needing manual review
flagged = [p for p in providers if "MANUAL REVIEW" in p.get("notes", "")]
print(f"Records needing review: {len(flagged)}")

# Find single-source risks
single_source = [p for p in providers if "SINGLE SOURCE" in p.get("notes", "")]
for r in single_source:
    print(r["supplier_name"], "|", r["process_code"])
```

#### JavaScript Example

```javascript
const BASE_URL = "http://localhost:7071/api";

async function getApprovedProviders() {
  const resp = await fetch(`${BASE_URL}/cms/providers`);
  if (!resp.ok) throw new Error((await resp.json()).error);
  return resp.json();
}

const providers = await getApprovedProviders();

// Active NDT providers
const activeNDT = providers.filter(
  p => p.process_category === "NDT" && p.approval_status === "Active"
);
console.log("Active NDT providers:", activeNDT.length);
```

#### curl

```bash
curl -s http://localhost:7071/api/cms/providers | python -m json.tool | head -60

# Count total records
curl -s http://localhost:7071/api/cms/providers | \
  python -c "import sys,json; d=json.load(sys.stdin); print(len(d), 'providers')"
```

---

### 5.3 Route: GET /api/cms/crosswalk

**Returns** the CMS-to-approved-process crosswalk from `cms_process_crosswalk.json`.

Use this route to determine which provider process codes are mandatory or conditional for a given CMS spec **before** validating an MTR.

#### Response Schema

```jsonc
{
  "cms_spec":                  "CMS-002",
  "material_scope":            "Base requirements for forgings and wrought products",
  "mandatory_process_codes":   ["LAB-001", "CHT-GEN"],
  "conditional_process_codes": ["CNT-002", "CNT-003", "CNT-004", "CNT-005", "CNT-007"],
  "conditional_trigger":       "NDT as required by PO or EPS flowdown",
  "typical_mtr_evidence":      ["Chemistry", "Tensile (mechanicals)", "Hardness", ...],
  "sop_notes":                 ["Baseline spec — always active for forgings/wrought products", ...]
}
```

#### Python Example

```python
import requests

BASE_URL = "http://localhost:7071/api"

def get_crosswalk() -> list[dict]:
    resp = requests.get(f"{BASE_URL}/cms/crosswalk", timeout=30)
    resp.raise_for_status()
    return resp.json()

crosswalk = get_crosswalk()

# Build a fast lookup dict
crosswalk_map = {entry["cms_spec"]: entry for entry in crosswalk}

# What does CMS-305 require?
codes = crosswalk_map["CMS-305"]
print("Mandatory:", codes["mandatory_process_codes"])
print("Conditional:", codes["conditional_process_codes"])

# Which specs require LAB-001?
lab_specs = [e["cms_spec"] for e in crosswalk
             if "LAB-001" in e["mandatory_process_codes"]]
print("Specs requiring LAB-001:", lab_specs)

# Is a process code valid for a given spec?
def is_valid_code(process_code: str, cms_spec: str) -> bool:
    entry = crosswalk_map.get(cms_spec, {})
    all_codes = (entry.get("mandatory_process_codes", []) +
                 entry.get("conditional_process_codes", []))
    return process_code in all_codes
```

#### JavaScript Example

```javascript
const BASE_URL = "http://localhost:7071/api";

async function getCrosswalk() {
  const resp = await fetch(`${BASE_URL}/cms/crosswalk`);
  if (!resp.ok) throw new Error((await resp.json()).error);
  return resp.json();
}

const crosswalk = await getCrosswalk();
const crosswalkMap = Object.fromEntries(crosswalk.map(e => [e.cms_spec, e]));

// Evidence required for CMS-107
const cms107 = crosswalkMap["CMS-107"];
console.log("Evidence:", cms107.typical_mtr_evidence);
console.log("SOP Notes:", cms107.sop_notes);
```

#### curl

```bash
curl -s http://localhost:7071/api/cms/crosswalk | python -m json.tool

# Show mandatory codes per spec
curl -s http://localhost:7071/api/cms/crosswalk | python -c "
import sys, json
for e in json.load(sys.stdin):
    print(e['cms_spec'], '->', e['mandatory_process_codes'])
"
```

---

### 5.4 Route: GET /api/cms/chunks

**Returns** all parsed chunk records from `cms-specs/cms_chunks.jsonl` filtered by `cms_number`.

Each chunk is a section extracted from a CMS spec PDF. Use this endpoint to:
- Retrieve full spec text for display or search
- Feed spec text into an LLM/AI pipeline for MTR validation reasoning
- Build a spec viewer organized by `canonical_section`

#### Query Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `cms_number` | string | **YES** | CMS spec number — case-sensitive (e.g. `CMS-002`) |

**Valid `cms_number` values:**

| Value | Scope |
|---|---|
| `CMS-002` | Base requirements — forgings and wrought products |
| `CMS-004` | Charpy / CVN impact framework |
| `CMS-107` | 4140 low-alloy steel |
| `CMS-118` | 4340 low-alloy steel |
| `CMS-303` | 17-4PH NACE route |
| `CMS-305` | Alloy 718 / API 6ACRA / NACE route |

#### Response Schema

```jsonc
{
  "doc": {
    "cms_number":     "CMS-002",
    "revision":       "L",
    "effective_date": "10/18/2024",
    "title":          "Revision L",
    "source_file":    "CMS-002.pdf"
  },
  "chunk": {
    "chunk_id":          "CMS-002::Heat Treating::text::p3-4",
    "type":              "text",
    "section_path":      ["Heat Treating"],
    "page_start":        3,
    "page_end":          4,
    "text":              "Equipment Qualification: Heat treatment operations shall be...",
    "canonical_section": "heat_treatment",
    "params": [
      { "type": "range", "lo": 25.0, "hi": null, "unit": "F", "context": "within 25F of QTC" }
    ]
  }
}
```

#### Canonical Section Labels

| Label | Description |
|---|---|
| `scope` | Spec applicability / purpose statement |
| `references` | Referenced standards (ASTM, API, ISO, SAE) |
| `heat_treatment` | Heat treat equipment, QTC, batch/continuous rules |
| `mechanical_properties` | Tensile, impact, and mechanical test requirements |
| `inspection` | Visual and dimensional inspection requirements |
| `nde` | Nondestructive examination requirements |
| `other` | All other extracted text blocks |
| `root` | Top-level document header/title block |

#### Python Example

```python
import requests

BASE_URL = "http://localhost:7071/api"

def get_cms_chunks(cms_number: str) -> list[dict]:
    resp = requests.get(
        f"{BASE_URL}/cms/chunks",
        params={"cms_number": cms_number},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()

chunks = get_cms_chunks("CMS-002")
print(f"Total chunks: {len(chunks)}")

# Document metadata
doc = chunks[0]["doc"]
print(f"{doc['cms_number']} Rev {doc['revision']} ({doc['effective_date']})")

# Filter to heat treatment sections
ht_chunks = [c for c in chunks if c["chunk"]["canonical_section"] == "heat_treatment"]
for c in ht_chunks:
    print(f"\n[p{c['chunk']['page_start']}] {c['chunk']['text'][:300]}")

# Extract all numeric parameters
for c in chunks:
    for param in c["chunk"]["params"]:
        print(f"  lo={param.get('lo')} hi={param.get('hi')} {param.get('unit')}")

# Full spec text for LLM ingestion
full_text = "\n\n".join(c["chunk"]["text"] for c in chunks)
print(f"Full spec: {len(full_text)} chars")
```

#### JavaScript Example

```javascript
const BASE_URL = "http://localhost:7071/api";

async function getCmsChunks(cmsNumber) {
  const url = new URL(`${BASE_URL}/cms/chunks`);
  url.searchParams.set("cms_number", cmsNumber);
  const resp = await fetch(url.toString());
  if (!resp.ok) throw new Error((await resp.json()).error);
  return resp.json();
}

const chunks = await getCmsChunks("CMS-002");

// Build a section index
const sectionIndex = {};
for (const c of chunks) {
  const sec = c.chunk.canonical_section;
  if (!sectionIndex[sec]) sectionIndex[sec] = [];
  sectionIndex[sec].push(c.chunk.text);
}
console.log("Sections found:", Object.keys(sectionIndex));
```

#### curl

```bash
# Retrieve CMS-002 chunks
curl -s "http://localhost:7071/api/cms/chunks?cms_number=CMS-002" | python -m json.tool | head -80

# Count chunks by section
curl -s "http://localhost:7071/api/cms/chunks?cms_number=CMS-002" | python -c "
import sys, json
from collections import Counter
counts = Counter(c['chunk']['canonical_section'] for c in json.load(sys.stdin))
for sec, n in sorted(counts.items()):
    print(f'  {sec}: {n}')
"

# Missing param → 400
curl -s http://localhost:7071/api/cms/chunks

# Unknown CMS → 200 with []
curl -s "http://localhost:7071/api/cms/chunks?cms_number=CMS-999"
```

---

### 5.5 Cross-Route Validation Pattern

This pattern combines all three endpoints to fully validate a provider against CMS rules — the core logic for the MTR intake engine.

```python
import requests

BASE_URL = "http://localhost:7071/api"

def validate_mtr_provider(
    cms_spec: str,
    provider_process_code: str,
    provider_name: str,
) -> dict:
    """
    Cross-reference a provider against:
      1) CMS crosswalk — is the process code applicable to this spec?
      2) Approved providers list — is the supplier Active for that code?
      3) Notes — are there flags (single-source, address review)?
    """
    # Step 1 — crosswalk check
    crosswalk = requests.get(f"{BASE_URL}/cms/crosswalk", timeout=30).json()
    crosswalk_map = {e["cms_spec"]: e for e in crosswalk}
    spec_entry = crosswalk_map.get(cms_spec)

    if not spec_entry:
        return {"valid": False, "reason": f"Unknown CMS spec: {cms_spec}"}

    all_valid_codes = (
        spec_entry["mandatory_process_codes"] +
        spec_entry["conditional_process_codes"]
    )
    if provider_process_code not in all_valid_codes:
        return {
            "valid": False,
            "reason": f"{provider_process_code} is not applicable to {cms_spec}",
        }

    # Step 2 — provider match
    providers = requests.get(f"{BASE_URL}/cms/providers", timeout=30).json()
    matches = [
        p for p in providers
        if p["process_code"] == provider_process_code
        and p["supplier_name"].lower() == provider_name.lower()
        and p["approval_status"] == "Active"
    ]
    if not matches:
        return {
            "valid": False,
            "reason": f"{provider_name} not found as Active for {provider_process_code}",
        }

    # Step 3 — flag check
    flags = [p["notes"] for p in matches if p["notes"]]
    return {
        "valid": True,
        "matched_sites": len(matches),
        "flags": flags,
    }


# Examples
print(validate_mtr_provider("CMS-002", "LAB-001", "Accu-Test Labs"))
# -> {"valid": True, "matched_sites": 1, "flags": []}

print(validate_mtr_provider("CMS-305", "CCS-612", "Houston Plating & Coatings"))
# -> {"valid": True, "matched_sites": 1, "flags": ["ADDRESS NEEDS MANUAL REVIEW; SINGLE SOURCE..."]}
```

---

### 5.6 Error Handling Reference

| HTTP Status | Meaning | Caller Action |
|---|---|---|
| `200` | Success | Parse body as JSON array |
| `400` | Missing required parameter | Fix query string before retrying |
| `500` | Unhandled server error | Log; do not retry immediately |
| `502` | Blob storage unreachable | Check Azurite; retry with exponential backoff |

**All error responses:**

```json
{ "error": "<message string>" }
```

**Recommended retry pattern:**

```python
import time, requests

def get_with_retry(url: str, params: dict = None, retries: int = 3) -> list | dict:
    for attempt in range(retries):
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 502 and attempt < retries - 1:
            time.sleep(2 ** attempt)  # 1s, 2s, 4s
            continue
        resp.raise_for_status()
```

---

## 6. Local Development Setup

### Prerequisites

| Requirement | Install Command |
|---|---|
| **Azurite** (blob emulator) | `npm install -g azurite@latest` |
| **Azure Functions Core Tools v4** | `npm install -g azure-functions-core-tools@4` |
| **Python venv** | `.venv\Scripts\pip install azure-functions azure-storage-blob` |

### Blob Container Setup

Upload the following blobs to the `cactus-whd` container in Azurite:

```
cactus-whd/
├── cms_approved_providers.json       ← root of container
├── cms_process_crosswalk.json        ← root of container
└── cms-specs/
    └── cms_chunks.jsonl              ← virtual subfolder
```

### Starting the Stack

```powershell
# 1. Start Azurite
azurite --silent --skipApiVersionCheck --location .azurite --debug .azurite\debug.log

# 2. Activate venv
.venv\Scripts\Activate.ps1

# 3. Start function app
func start
```

**Expect this startup output:**

```
Functions:
  http_cms_providers: [GET] http://localhost:7071/api/cms/providers
  http_cms_crosswalk: [GET] http://localhost:7071/api/cms/crosswalk
  http_cms_chunks:    [GET] http://localhost:7071/api/cms/chunks
```

### Settings (`local.settings.json`)

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "BLOB_CONNECTION_STRING": "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
  }
}
```

---

### 6.1 Azurite Troubleshooting

<details>
<summary><strong>Error: API version not supported</strong></summary>

The `azure-storage-blob` SDK version is newer than Azurite.

**Fix (immediate):** Enable `skipApiVersionCheck`

```powershell
azurite --silent --skipApiVersionCheck
```

Or in VS Code settings: `Azurite: Skip Api Version Check ✓`

**Fix (permanent):** Update Azurite

```powershell
npm install -g azurite@latest
```

</details>

<details>
<summary><strong>Error: Authorization failure / AuthorizationFailure</strong></summary>

Credentials in connection string don't match Azurite.

**Checklist:**

| Field | Expected Value |
|---|---|
| `AccountName` | `devstoreaccount1` |
| `BlobEndpoint` | `http://127.0.0.1:10000/devstoreaccount1` |
| Azurite ports | `10000` (blob), `10001` (queue), `10002` (table) |

**Verify ports are listening:**

```powershell
netstat -an | findstr "10000 10001 10002"
```

**Verify container and blobs exist:**

```python
from azure.storage.blob import BlobServiceClient
cs = "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
svc = BlobServiceClient.from_connection_string(cs)
for b in svc.get_container_client("cactus-whd").list_blobs():
    print(b.name)
```

</details>

---

## 7. JSON Artifact Reference

| File | Location | Purpose |
|---|---|---|
| `cms_approved_providers.json` | `cactus-whd/` (blob root) | Approved sub-supplier + site + process code registry |
| `cms_process_crosswalk.json` | `cactus-whd/` (blob root) | CMS-to-process-code rule matrix |
| `cms_chunks.jsonl` | `cactus-whd/cms-specs/` | Parsed CMS spec PDF chunks (JSONL, one record per line) |

### crosswalk entry structure

```jsonc
{
  "cms_spec":                  "CMS-002",      // CMS identifier
  "material_scope":            "...",           // plain-English scope
  "mandatory_process_codes":   ["LAB-001"],     // always required
  "conditional_process_codes": ["CNT-002"],     // required per PO/EPS
  "conditional_trigger":       "NDT per PO",   // when conditional codes activate
  "typical_mtr_evidence":      ["Chemistry"],  // required MTR data fields
  "sop_notes":                 ["..."]         // enforcement notes and risk flags
}
```

### Intended use in intake engine

1. Resolve `cms_spec` from PO + material master
2. Load crosswalk entry → get `mandatory_process_codes` + `conditional_process_codes`
3. For each test line item on MTR: match provider against `cms_approved_providers.json`
4. Drive evidence field completeness checklist from `typical_mtr_evidence`
5. Enforce `sop_notes` flags in disposition logic

---

*End of Guide — Cactus WHD Developer & SOP Reference · 2026-03-02*
