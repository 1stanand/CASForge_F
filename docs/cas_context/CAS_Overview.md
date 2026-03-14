# FinnOne Neo — CAS Foundation Document

Purpose: Context document for the ATDD AI Assistant project.
This document explains the CAS system at a level sufficient for understanding
the ATDD automation repository. It is not a technical CAS specification.

## FINNONE NEO — OVERVIEW

FinnOne Neo is a digital lending platform by Nucleus Software.
It has three modules relevant to this project:

CAS — Customer Acquisition System (loan origination — our primary focus)
LMS — Loan Management System (post-disbursal loan management — out of scope)
Common — Shared data handling module used by both CAS and LMS

## CAS — WHAT IT DOES

CAS handles the complete loan origination journey.
From the first customer contact (lead capture) through to full loan disbursal.
It works across multiple loan types called Lines of Business (LOBs).

## LINES OF BUSINESS (LOBs)

CAS supports 18 LOBs. Each has a short code used throughout the system and ATDD repo.

Mortgage Loans:
HL — Home Loan
LAP — Loan Against Property
MHF — Micro Housing Finance

Movable Asset Loans:
Auto — Auto Loan
CV — Commercial Vehicle Loan
CEQ — Commercial Equipment Loan
TL — Tractor Loan (Farm Equipment Loan)

Other Loans:
Omni — Omni Loan (special — see below)
Agri — Agriculture Loan
PL — Personal Loan
CC — Credit Card Loan
EL — Education Loan
FAS — Finance Against Security (special — see below)
CD — Consumer Durable Loan (also called Proposal)
SHG — Self Help Group Loan
JLG — Joint Liability Group Loan
Corp — Multi Facility Loan / Corporate (special — see below)
GL — Gold Loan (special — see below)

Special LOBs:
Omni — Allows multiple loan types under one application.
A customer can take HL + PL + Auto simultaneously in one Omni application.
Screens are the same as standard LOBs but combined.
In scope for ATDD but treated as a combined LOB.

Corporate — Very technical, non-traditional structure.
Sparse in ATDD repo. Not explained in detail. Low priority.

FAS — Finance Against Securities. Loan against stocks.
Has unique screens and some unique stages.
Not a traditional loan flow. Low priority for ATDD generation.

GL — Gold Loan. Similar context to FAS.
Not a traditional flow. Low priority for ATDD generation.

For ATDD purposes:
Primary LOBs (standard flow, well represented in repo):
HL, LAP, MHF, Auto, CV, CEQ, TL, Agri, PL, CC, EL, CD, SHG, JLG, Omni
Secondary LOBs (sparse in repo, non-standard):
Corporate, FAS, GL

## THE STAGE FLOW

A loan application moves through stages sequentially.
Each stage must be completed before the application moves to the next.
The Move to Next Stage button validates all mandatory data and advances the application.

Most LOBs follow this flow:

Quick Lead (rarely used — basic lead before application starts)
↓
Lead Details ← most LOBs start here
↓
Login Acceptance
↓
KYC ← completing KYC adds applicant to Global Customer Database (GCD)
↓
DDE ← SHG, JLG, Corporate, FAS start here (skip Lead/Login/KYC)
↓
Recommendation
↓
Credit Approval ← most critical stage
↓
Reconsideration ← mandatory
↓
Post Approval (PDoc)
↓
Disbursal Initiation
↓
Disbursal Author ← loan is disbursed

Parallel Stages (non-blocking, optional):
These begin after KYC because KYC completion places the applicant in the GCD.
Once in GCD, these can start independently and run in parallel to the main flow.
They do NOT block disbursal. They can even complete after Disbursal Author.
They can be waived from their initiation stage.

CII → CIV → CIC Collateral Investigation (Initiation, Verification, Completion)
FII → FIV → FIC Field Investigation (Initiation, Verification, Completion)
RCU Init → RCU Verify → RCU Complete Risk Containment Unit

For LOBs starting at DDE (SHG, JLG, Corporate, FAS):
Their KYC, FI, CI, and RCU can be handled within Credit Approval stage.

Post-Disbursal Flow (App Update / Re-initiation):
For customers who want to modify their loan after disbursal (e.g. increase amount):

Re-initiate (App Update)
↓
App Update Recommendation
↓
App Update Approval
↓
Back to Credit Approval

## SCREEN STRUCTURE WITHIN A STAGE

Every stage contains multiple tabs.
Each tab contains one or more screens.
Each screen contains sections and accordions.

Example — Lead Details stage:

Tab: Applicant Information
Screen: Add Applicant / Add Co-Applicant
Individual Applicant: Personal Info, Documents, Education, Financial, Employment, Bank Details
Non-Individual Applicant: Organisation Name, Organisation Details, Guarantor, Director/Partner Details

Tab: Loan Details
Screen: Sourcing Information (branch, channel, product, scheme, loan type, requested amount)
Screen: Asset / Property Details
Screen: Repayment Parameters
Screen: Receipts

Tab: Documents
(Not interacted with heavily in ATDD at Lead Details stage)

What is mandatory changes by stage:
Lead Details — most fields optional
DDE — documents become mandatory, asset/property details become mandatory,
repayment parameters become mandatory

Move to Next Stage validation:
In-page validations — immediate feedback as forms are filled
Stage-level validations — cross-screen and cross-field checks when button is clicked
Example: negative LTV (requested amount vs asset value mismatch) caught at Move to Next Stage

## CREDIT APPROVAL — SPECIAL NOTE

Credit Approval is the most complex stage.
It is sometimes called the Underwriter stage.
It has many screens, tabs, and accordions.

Two sub-processes can occur within Credit Approval:

Deviations:
Can be raised manually by the user or triggered automatically by system rules.
Example rule: applicant age over 60 requesting a large loan amount.
Deviations are handled on the main Credit Approval screen.

Committee:
Can be initiated manually or triggered automatically by rules.
When initiated, it behaves like a mini-stage.
All assigned committee members must log in and provide their decisions.
Application cannot move to Next Stage until committee decisions are complete.

Both deviations and committee are sub-processes within Credit Approval,
not separate stages in the main flow.

## RECONSIDERATION — NOTE

Reconsideration is mandatory. It is not optional.
It sits between Credit Approval and Post Approval.
Every application passes through it.

## SCREEN CONSISTENCY ACROSS LOBs

Screens are largely consistent across LOBs at the same stage.
Minor variations exist based on loan type:
Mortgage LOBs (HL, LAP, MHF) — have Property Details screens
Movable Asset LOBs (Auto, CV, CEQ, TL) — have Asset Details screens
Other LOBs — relevant screens for their context

This consistency is why the ATDD annotation system uses
@StageName and @ScreenName — scenarios written for one LOB's screen
often apply to the same screen across multiple LOBs.

## WHAT THIS MEANS FOR THE ATDD REPOSITORY

The ATDD repo reflects this structure directly.
Feature files are organised around stages and screens.
Annotations tag which LOB, stage, and screen a scenario applies to.
The Examples table drives which LOB + stage combinations a scenario runs against.
The 17-18 LOBs × 10+ stages × multiple screens = a very large test matrix.
This is why the dictionary-based expansion system exists in the feature files.
