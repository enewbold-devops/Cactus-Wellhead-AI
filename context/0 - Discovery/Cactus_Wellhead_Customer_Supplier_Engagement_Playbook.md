# Cactus Wellhead (Cactus, Inc. — WHD)  
## Customer & Supplier Engineering Engagement Playbook  
*Export date:* 2026-02-27

> This document consolidates our conversation into a detailed, narrative, and “interactive” Markdown artifact.  
> Interactive elements include: a clickable Table of Contents, collapsible sections, and ready-to-use checklists/matrices.

---

## Table of Contents
- [1. Company and Offering Context](#1-company-and-offering-context)
- [2. Customer Deep Dive](#2-customer-deep-dive)
- [3. Translating Customer Engineering Requirements Into Controlled Specs](#3-translating-customer-engineering-requirements-into-controlled-specs)
- [4. Supplier Engagement Methodology](#4-supplier-engagement-methodology)
- [5. Three Supplier Scenarios](#5-three-supplier-scenarios)
  - [5.1 Raw Forging House](#51-raw-forging-house)
  - [5.2 Machine Shop](#52-machine-shop)
  - [5.3 Coatings / Welding / Cladding](#53-coatings--welding--cladding)
- [6. Embedded Forms and How They Tighten Controls](#6-embedded-forms-and-how-they-tighten-controls)
- [7. Calibration Procedures and Master Specifications](#7-calibration-procedures-and-master-specifications)
- [8. Integrated Matrices and Checklists](#8-integrated-matrices-and-checklists)
- [9. Objective Evidence Pack by Supplier Type](#9-objective-evidence-pack-by-supplier-type)
- [10. Appendix: Source Files](#10-appendix-source-files)

---

## 1. Company and Offering Context

Cactus Wellhead (Cactus, Inc. — WHD) manufactures and services **surface pressure control** equipment used across:
- **Onshore and offshore drilling**
- **Completions / hydraulic fracturing**
- **Production operations**

The core business involves designing/manufacturing, selling/renting, and field-servicing pressure control assemblies and related components.  
This drive for uptime and safety creates a strong linkage between customer engineering requirements and controlled supplier processes.

---

## 2. Customer Deep Dive

### 2.1 Customer “types” (how to segment the base)
Practical segmentation used in pressure control:
1. **Large E&Ps** (often standardized programs; high repeatability)
2. **Private operators** (speed + responsiveness; lean procurement)
3. **Majors / IOCs** (high qualification rigor; slow-but-sticky once approved)
4. **International / NOC-heavy customers** (more installed-base aftermarket economics, longer-cycle planning)

### 2.2 Why customers “stick” (sole-provider behavior)
Pressure control is operationally sensitive. Once an operator standardizes on:
- wellhead designs,
- installation procedures,
- spare parts,
- field service playbooks,

switching becomes expensive and risky. The supplier relationship becomes “programmatic.”

### 2.3 Concentration risk (how to think about it)
A small number of large programs can drive outsized revenue.  
From a supplier-engagement standpoint, this makes “auditability” and “defect containment” critical because a single systemic defect can affect a wide installed base.

---

## 3. Translating Customer Engineering Requirements Into Controlled Specs

Customer requirements are typically provided as:
- governing standards (API 6A/ISO, customer specs),
- service conditions (temperature class; sour vs non-sour),
- metallurgy requirements (chemistry limits, mechanicals, CVN/Charpy, hardness limits),
- heat treat windows and controls,
- inspection & documentation requirements.

### 3.1 The “Big Five” requirement domains
1. **Chemical composition**  
2. **Mechanical properties** (YS/UTS/elongation/RA, etc.)  
3. **Charpy impact (CVN)** requirements  
4. **Heat treatment parameters** (Q&T, normalize/temper, PWHT, etc.)  
5. **Hardness testing rules** (scale, location, frequency, sour-service maxes)

### 3.2 Key discipline
These cannot be optimized independently.  
For example, CVN and hardness are direct outputs of heat treatment history and chemistry.  
Therefore, Cactus-style control requires mapping these into:
- CTQs (critical-to-quality characteristics)
- MPP steps (Manufacturing Process Plan)
- PQP/ITP hold points (Product Quality Plan / Inspection & Test Plan)
- objective evidence that is traceable to heat/lot/serial

---

## 4. Supplier Engagement Methodology

### 4.1 Core engagement spine
1. **Scope**: define part family + service envelope  
2. **Freeze**: PO + drawings + ordering documents are the authoritative spec set  
3. **Approve**: supplier onboarding + process assessment and/or product qualification  
4. **Translate**: requirements → CTQs → MPP + PQP/ITP  
5. **Execute**: controlled manufacturing + calibrated measurement + complete records  
6. **Control change**: no silent changes; deviations require formal approval (SDR)

### 4.2 Roles and interfaces
- **Sourcing / Buyer**: commercial interface, PO control
- **SQE (Supplier Quality Engineer)**: technical/quality interface
- **Customer Engineering**: upstream requirement owner

---

## 5. Three Supplier Scenarios

> The three scenarios represent the most common supplier archetypes in pressure-control manufacturing.

---

## 5.1 Raw Forging House

### What can go wrong (risk picture)
- Chemistry drift (S/P cleanliness, alloying limits)
- Heat treat excursions (austenitize/temper windows, quench control)
- CVN failures from microstructure/sampling/location/orientation errors
- Hardness out-of-window (especially sour service)
- Traceability loss (heat mixing)

### How Cactus engages (control model)
- Require an **MPP** that explicitly includes:
  - approved mills / melt sources,
  - heat treat steps and parameter windows,
  - sample plans tied to heat treat lot,
  - hardness mapping plan,
  - CVN location/orientation rules,
  - all critical sub-tier providers.

### Typical ITP hold/witness points
- HOLD: raw material receipt verification (CMTR review + marking)
- HOLD/WITNESS: heat treat load and chart review
- HOLD: test coupon selection verification (location/orientation)
- HOLD: hardness map acceptance
- HOLD: final record pack completeness

---

## 5.2 Machine Shop

### What can go wrong (risk picture)
- CTQ dimensional drift (seal grooves, bores, concentricity/runout)
- Thread form / gauging nonconformance; galling risk
- Surface finish issues on sealing faces
- NDE performed by unqualified sub-tier
- Mixed material / lost traceability during routing

### How Cactus engages (control model)
- Drawings + inspection notes become the “spec weapon”
- Require a machine-shop MPP with:
  - router steps, in-process checks,
  - CMM program control and gage management,
  - thread gage plan and records,
  - sub-tier listing for NDE/coatings (must be approved),
  - preservation and packaging controls.

### Typical ITP hold/witness points
- HOLD: first-piece approval for CTQ datums
- WITNESS: CMM program verification (as needed)
- HOLD: thread gaging + seal surface finish acceptance
- HOLD: NDE close-out review
- HOLD: pre-ship record pack + preservation

---

## 5.3 Coatings / Welding / Cladding

### What can go wrong (risk picture)
- HAZ hardness too high (SSC risk in sour service)
- PWHT excursions; brittle microstructures; toughness loss
- Coating adhesion/coverage defects; wrong coating spec
- Cladding dilution affecting corrosion resistance
- NDE misses or poor repair governance

### How Cactus engages (control model)
Because these are **special processes**, final inspection alone is insufficient.  
Control requires:
- procedure qualification (WPS/PQR or coating procedure),
- operator qualification (welder certs, NDE certs),
- environmental and parameter recording,
- hardness traverses (weld/HAZ/base),
- explicit rework limits and approval gates.

### Typical ITP hold/witness points
- HOLD: procedure approval prior to production
- WITNESS: first-run parameter verification
- HOLD: PWHT chart review prior to release
- HOLD: hardness traverse acceptance
- HOLD: NDE close-out + repair verification
- HOLD: final coating acceptance (DFT/adhesion/holiday, as applicable)

---

## 6. Embedded Forms and How They Tighten Controls

This section ties our three-scenario methodology to the **actual Cactus forms** you provided.

### 6.1 Approved Sub-Supplier List (2/12/2026)
Purpose: hard constraints on *who* may perform special processes and inspections.

Common “must-control” outsourced steps:
- Nitriding (e.g., QPQ / Gas nitriding)
- Plating (copper, nickel)
- Coatings (Xylan variants, etc.)
- Heat treatment “per Cactus Wellhead specs”
- NDE methods (PT/MT/UT/RT)

**Rule of engagement:**  
If a supplier intends to outsource any of these steps, the PO/ITP must require sub-tier selection from the approved list (or require pre-approval via the SQE route).

### 6.2 Supplier Deviation Request (MSP 5.6-1 Rev B)
Purpose: the only acceptable path for shipping “out-of-spec but dispositionable” items.

Mechanics:
- Supplier completes SDR and emails it to the Cactus buyer on the PO.
- SDR must include PO/line, part/drawing rev, and traceability identifiers (heat & serials).
- Disposition is controlled (Accept / Rework / Scrap) with Engineering + Quality approval.
- If accepted/reworked: parts must be marked/tagged with SDR number; SDR copy must ship with certs/BOL.

**Rule of engagement:**  
No verbal approvals. No email-only approvals. SDR must exist and be tied to shipment evidence.

---

## 7. Calibration Procedures and Master Specifications

This section integrates calibration governance and master specs into supplier engagement controls.

### 7.1 Calibration governance (CCP-500 umbrella)
Key points captured in your calibration notes:
- Only tools in calibration can be used for measurement and monitoring.
- If CCP-500 conflicts with a specific CCP, the specific CCP governs.
- Pressure gauge intervals begin at 3 months until stability history exists; can be extended in 3-month steps to a max of 1 year.
- “Stability history” includes acceptable variance from master-to-test readings.
- Welding control calibration begins at 6 months until history exists; can extend to a max of 1 year.
- Multi-gas monitors require bump testing prior to use.

### 7.2 Calibration inventory and frequencies (Rev U CSV)
Your calibration CSV enumerates equipment categories and intervals (examples include pressure gauges for product testing, hardness testers, dimensional tools, etc.).  
This is the backbone for ensuring CIR/CNT acceptance is defensible.

### 7.3 Master Specifications (CSV)
The Master Specifications list provides the “library of controlled requirements” that suppliers must work to. Examples include:
- Dimensional inspection
- Hardness testing
- NDE (PT/MT/UT/RT)
- Heat treatment services
- Welding with/without PWHT
- Coating and nitriding specifications
- Outsourced calibration specification

**How to use this in engagement:**  
For each PO line item, reference the applicable Master Spec(s) explicitly and make them the contract basis for acceptance.

---

## 8. Integrated Matrices and Checklists

### 8.1 Integrated control matrix (template)
Use this as the standard “translation layer” for any supplier:

| Requirement Domain | Customer Requirement | Cactus Master Spec / Procedure | Supplier Control Artifact | Verification / Evidence |
|---|---|---|---|---|
| Chemistry | e.g., max S/P, alloy limits | Material / purchasing spec | MPP + CMTR controls | CMTR + traceability map |
| Mechanical | YS/UTS/EL | inspection/testing spec | PQP/ITP | Tensile report |
| CVN/Charpy | temp, energy, min single | testing spec | PQP/ITP + sample plan | CVN report (full data) |
| Heat Treat | Q&T windows | HT services spec | MPP + furnace controls | HT charts + load TC |
| Hardness | max/min, locations | hardness testing spec | hardness map plan | hardness map + method |

### 8.2 Supplier engagement checklist (universal)
- [ ] PO references applicable Master Spec(s) for the part
- [ ] Supplier reviewed drawings/ordering documents; ambiguities resolved
- [ ] Supplier MPP submitted with:
  - [ ] manufacturing location
  - [ ] sub-tier list (mills, HT, NDE, coatings, labs)
  - [ ] step-by-step plan and sign-offs
- [ ] Sub-tier suppliers are on **Approved Sub-Supplier List**
- [ ] PQP/ITP defines hold/witness points and evidence
- [ ] Measurement equipment in calibration per CCP-500 + CCP-XXX
- [ ] Any nonconformance routed through SDR; no shipment without disposition
- [ ] Shipment includes complete record pack and traceability reconciliation

---

## 9. Objective Evidence Pack by Supplier Type

### 9.1 Forging supplier record pack
- CMTR/MTR
- Heat treat charts (all cycles)
- Mechanical test report(s)
- CVN impact report(s)
- Hardness map
- NDE reports (if applicable)
- Traceability map (heat → forging → serial → shipment)
- Any SDR documentation (if applicable)

### 9.2 Machine shop record pack
- Bubble drawing / dimensional report (CMM outputs)
- Thread gage records (as required)
- Surface finish verification (seal areas)
- NDE reports + repair documentation (as applicable)
- Coating/plating certs (if routed)
- Preservation/packaging evidence
- Traceability map
- SDR documentation (as applicable)

### 9.3 Special process record pack (weld/clad/coating)
- Procedure qualification (WPS/PQR or coating procedure)
- Operator qualifications (welder, NDE techs)
- Environmental logs (coatings) / parameter logs (welding)
- PWHT charts (if applicable)
- Hardness traverse results (weld/HAZ/base)
- NDE reports + repair cycle documentation
- Final acceptance tests (DFT/adhesion/holiday, as required)
- Traceability map
- SDR documentation (as applicable)

---

## 10. Appendix: Source Files

### 10.1 Forms
- **Cactus-Wellhead-Approved-Sub-Suppliers-2-12-2026.pdf**  
  Approved sub-tier providers for specific processes (coatings, nitriding, NDE, heat treat, etc.)

- **Form-MSP-5.6-1-Rev-B-Supplier-Deviation-Request.pdf**  
  Formal deviation request and disposition workflow (accept/rework/scrap; shipment tagging and paperwork requirements)

### 10.2 Calibration
- **Callibration Procedure Notes.txt**  
  CCP-500 umbrella notes including pressure gauge stability history rules and welding control calibration intervals.

- **Callibration Procedure revU.csv**  
  Calibration inventory and intervals by tool category.

### 10.3 Master Specs
- **Master Specifications.csv**  
  Master specification library used to contract and govern supplier work.

---

*End of document.*
