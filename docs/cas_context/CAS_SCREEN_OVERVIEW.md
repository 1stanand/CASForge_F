**CASForge --- CAS Screen Name Reference**

_Canonical screen names used in screen_context column and retrieval
filter chain_

Author: Anand Singh \| Status: Living Document --- update as new screens
discovered

**1. Purpose**

This document defines the canonical screen names used throughout
CASForge --- in the screen_context column of the steps catalogue, in the
retrieval filter chain, and as values in the Impacted Areas screen
selection on the UI.

Every entry in the SCREEN_NAME_MAP in config/normalisation.py must have
a corresponding entry here. When new screens are discovered during
catalogue builds or when new LOBs/stages are added to CAS, both this
document and the map must be updated together.

> _• The canonical name is what gets stored in the database. Aliases are
> what the parser recognises in step text. If a new alias is found
> producing garbage in screen_context, add it to the map --- don\'t just
> fix the data._

**2. How Screen Context Works**

The parser infers screen context from navigation anchor steps --- steps
whose text contains keywords like opens, navigates to, moves to, selects
(tab/accordion/drawer).

When an anchor step is found, the screen name is extracted, cleaned, and
looked up in SCREEN_NAME_MAP. If found, the canonical name is stored in
screen_context on that step and all subsequent steps in the same
scenario until the next anchor step.

If the extracted phrase is not in the map, it is rejected and
screen_context remains null. This is intentional --- a clean null is
better than a dirty string.

> _• selects is only treated as a navigation anchor when immediately
> followed by a UI container word: tab, accordion, drawer, screen, or
> page. selects collateral type as is a field interaction and is
> ignored._
>
> _• Steps using the LogicalID prerequisite chain (Given all
> prerequisite\...) are not parsed for screen context --- the navigation
> step lives in a prior scenario that is not traversed at parse time._
>
> _• Estimated coverage after a full parse: 30-50% of steps will have
> screen_context populated. The remainder are either LogicalID-chained
> scenarios or steps with no navigation anchor above them._

**3. Screen Reference by Stage**

Screens are organised by stage for readability. Many screens appear in
multiple stages --- they have one canonical name regardless of which
stage they appear in. The stage filter in retrieval handles
stage-specificity.

■ **Stage 1 --- Lead Details**

_Default landing screen: Applicant Information_

---

**Canonical Screen **Known Aliases / **Notes**
Name** Variants**

Applicant applicant info, applicant Default landing. Hosts
Information details, applicant piano tabs below.
profile, add applicant

Personal personal info, personal Piano tab under Applicant
Information details Information.

Employment Details employment, occupation Piano tab under Applicant
details Information.

Financial Details financial, income details Piano tab under Applicant
Information.

Bank Details bank, bank account Piano tab under Applicant
details Information.

Re-KYC rekyc, re kyc Piano tab.
Configuration-based ---
may not appear in all
LOBs.

Need Analysis need analysis section Separate tab on Lead
Details.

Loan Information loan details, loan info Tab. Hosts piano tabs
below.

Sourcing Details sourcing information, Piano tab under Loan
sourcing info, sourcing Information.

Property Details property, property and Piano tab under Loan
registration details Information. ML loans
only (HL, LAP, MHF).

Lien Details lien Sub-tab under Property
Details.

Cersai Details cersai Sub-tab under Property
Details.

Asset Details asset detail Piano tab under Loan
Information. Single-asset
MAL loans.

Asset Requested Piano tab under Loan
Information. Multi-asset
MAL loans.

Repayment loan parameters, loan Piano tab under Loan
Parameters parameter, repayment Information. Disabled at
Lead Details --- enabled
from DDE onwards.

Receipts receipt, receipts section Piano tab under Loan
Information.

Documents document, document tab, Separate tab.
documents tab

Personal Discussion Separate tab.

Balance Transfer bt details, bt Visible only when
application type is
Balance Transfer in
Sourcing.

Card Details card detail Visible for Credit Card
LOB.

Collateral collateral tab, Tab for secondary
collateral screen, collaterals.
collateral page

Collateral Details collateral detail Detail view within
Collateral tab.

---

■ **Stage 2 --- Login Acceptance**

_Default landing screen: Login Acceptance_

---

**Canonical Screen **Known Aliases / **Notes**
Name** Variants**

Login Acceptance login Default landing and
primary screen for this
stage.

Applicant (same aliases as above) Same screen as Lead
Information Details --- same piano
tabs.

Documents (same aliases as above) Same screen as Lead
Details.

---

■ **Stage 3 --- KYC**

_Default landing screen: KYC_

---

**Canonical Screen **Known Aliases / **Notes**
Name** Variants**

KYC kyc details, know your Default landing.
customer, kyc screen Completing KYC adds
applicant to GCD.

Applicant (same aliases as above) Same screen as previous
Information stages.

Documents (same aliases as above) Same screen as previous
stages.

---

■ **Stage 4 --- DDE**

_Default landing screen: Loan Information_

---

**Canonical Screen **Known Aliases / **Notes**
Name** Variants**

Loan Information (same aliases as above) Default landing at DDE.
Repayment Parameters now
enabled.

Repayment (same aliases as above) Now editable --- was
Parameters disabled at Lead Details.

Applicant (same aliases as above) Same as before.
Information

Documents (same aliases as above) Mandatory documents
required at DDE.

Deviations deviation, deviation Configuration-based. May
section, business not appear in all LOBs.
deviations, credit  
 deviations, manual  
 deviation, raise  
 deviation

Property Details (same aliases as above) Now mandatory for ML
loans.

Asset Details (same aliases as above) Now mandatory for MAL
loans.

Collateral (same aliases as above) Secondary collaterals.

---

■ **Stage 5 --- Recommendation**

_Default landing screen: Recommendation_

---

**Canonical Screen **Known Aliases / **Notes**
Name** Variants**

Recommendation recommendations Default landing and
primary screen for this
stage.

---

■ **Stage 6 --- Credit Approval**

_Default landing screen: Underwriter Decision_

_Additional screens accessible via More Options button. Decision Drawer
opens from bottom-right of page._

---

**Canonical Screen **Known Aliases / **Notes**
Name** Variants**

Underwriter credit approval, Default landing. Most
Decision underwriter decisions complex screen in the
system.

Credit Decisioning credit decision Drawer or sub-section
within Credit Approval.

Decision decisions, decision Tab inside Decision
details Drawer.

Product Type Tab inside Decision
Decisions Drawer.

Card Type Decisions Tab inside Decision
Drawer. Credit Card LOB
only.

Approval Checklist Tab inside Decision
Drawer.

Committee committee approval, Sub-process within Credit
committee decision Approval. Behaves like a
mini-stage.

Deviations (same aliases as above) Inline on Underwriter
Decision screen.

Property Details (same aliases as above) View-only table on
screen. Click View
Details to open full
screen.

KYC (same aliases as above) View-only table on
screen.

Applicant (same aliases as above) Accessible via More
Information Options.

Repayment (same aliases as above) Accessible via More
Parameters Options.

Documents (same aliases as above) Accessible via More
Options.

Balance Transfer (same aliases as above) Accessible via More
Options when applicable.

CAM Report cam Accessible via More
Options.

Score Card scorecard Accessible via More
Options.

---

■ **Stage 7 --- Reconsideration**

_Default landing screen: Reconsideration_

---

**Canonical Screen **Known Aliases / **Notes**
Name** Variants**

Reconsideration Default landing.
Mandatory stage --- every
application passes
through it.

Applicant (same aliases as above) Same as before.
Information

---

■ **Stage 8 --- Post Approval**

_Default landing screen: Post Approval_

---

**Canonical Screen **Known Aliases / **Notes**
Name** Variants**

Post Approval pdoc, post approval Default landing.
documents

Documents (same aliases as above) Post-approval documents.

Applicant (same aliases as above) Same as before.
Information

Deviations (same aliases as above) Configuration-based.

Repayment repayment instrument, Repayment instrument
Instruments repayment instrument entry.
details

---

■ **Stage 9 --- Disbursal**

_Default landing screen: Disbursal_

_Also called Disbursal Maker or Disbursal Author in some versions._

---

**Canonical Screen **Known Aliases / **Notes**
Name** Variants**

Disbursal disbursal details, Default landing.
disbursement details,  
 disbursal entry,  
 disbursal main, disbursal
maker, disbursal author

Repayment (same aliases as above) Accessible at Disbursal.
Parameters

Documents (same aliases as above) Same as before.

Deviations (same aliases as above) Same as before.

Repayment (same aliases as above) Same as before.
Instruments

---

**4. Parallel Stage Screens**

These stages run in parallel to the main flow after KYC. They are
non-blocking and do not prevent disbursal.

■ **Collateral Investigation (CII → CIV → CIC)**

---

**Canonical Screen **Known Aliases / **Notes**
Name** Variants**

Collateral cii, collateral First parallel stage for
Investigation investigation collateral.
Initiation

Collateral civ  
 Investigation  
 Verification

Collateral cic  
 Investigation  
 Completion

---

■ **Field Investigation (FII → FIV → FIC)**

---

**Canonical Screen **Known Aliases / **Notes**
Name** Variants**

Field Investigation fii, field investigation First parallel stage for
Initiation field investigation.

Field Investigation fiv  
 Verification

Field Investigation fic  
 Completion

---

■ **Risk Containment Unit (RCU)**

---

**Canonical Screen **Known Aliases / **Notes**
Name** Variants**

RCU Initiation rcu init, rcu, rcu  
 initiation

RCU Verification rcu verify, rcu  
 verification

RCU Completion rcu complete, rcu  
 completion

RCU Referral rcu referral

---

**5. LOB-Specific Screens**

These screens appear only for specific LOBs or configurations.

---

**Screen** **LOB / Context** **Notes**

Investor Details HL, LAP ---  
 investment-related  
 applicants

Bond Allocation Securities-related LOBs  
 (FAS)

Metal Allocation Gold Loan (GL)

Share Holding Corporate, FAS  
 Details

Corporate Rating Corporate LOB

Partners & partners and directors, Non-individual applicants
Directors partners directors --- Corporate, LAP.

SHG Details shg details Self Help Group LOB only.

Gold Valuation Gold Loan (GL) only.

Land Holding Agricultural LOBs (Agri,
Summary TL).

Crop Details Agricultural LOBs.

Cattle Details Agricultural LOBs.

Subsidy Details subsidy Agricultural and government
scheme LOBs.

VAP Details vap detail, vap Value Added Products ---
appears when VAP configured.

Waiver Initiation waiver Charge waiver workflow.

Waiver  
 Verification

Waiver Approval

---

**6. Maintenance Instructions**

When to update this document and normalisation.py:

- A new screen appears in the repo that is not in the map --- add it
  here and to SCREEN_NAME_MAP

- A new alias variant is found producing garbage in screen_context ---
  add the alias to the map entry

- A new LOB or stage is added to CAS --- add its screens here and to
  the map

- A screen is renamed in CAS --- add the new name as canonical, keep
  old name as alias

> _• Always run \--full-reparse after updating normalisation.py if stage
> normalisation or LOB normalisation was changed. Incremental parse is
> sufficient if only SCREEN_NAME_MAP was updated --- screen_context is
> derived at parse time so only newly parsed or changed files will pick
> up the new entries. Run \--full-reparse to backfill existing files._
>
> _• The map currently has 182 entries covering approximately 70% of
> screens in the system. As the remaining 30% are discovered through
> catalogue inspection, add them here._

_End of Document --- living reference, update continuously_
