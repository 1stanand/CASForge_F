**ATDD Repository**

Context, Architecture & Known Challenges

_Internal Project Documentation_

**1. Project Origin**

In December 2023, the organisation decided to move away from the
existing Robot Framework automation and adopt a full BDD approach using
ATDD (Acceptance Test Driven Development).

A new team was recruited to build the ATDD framework from scratch. A key
oversight at this stage was the failure to consult existing automation
testers --- engineers who had deep knowledge of the system\'s real
challenges, particularly around CAS (Credit Application System) flow
behaviour.

This decision would prove costly later. The core characteristic of CAS
is that it is heavily reliant on stage movement and end-to-end flow, not
just stage-specific screen testing. This was not factored into the
initial framework design.

**2. Initial Approach --- Screen and Stage Coverage**

The new team\'s initial strategy was sound from a unit-coverage
perspective. They targeted individual screens and stages, writing
scenario outlines such as:

> Scenario Outline: Customer should be able to save Sourcing decisions
> with mandatory fields only.
>
> Given \...
>
> When \...
>
> Then \...
>
> Examples:
>
> \| ApplicationStage \| ProductType \|

However, this immediately exposed a volume problem. CAS supports 18
Lines of Business (LOBs / Products) and each has multiple editable
stages. For the Sourcing page alone:

- 18 Products x 5 Stages (Lead Details, Login Acceptance, KYC, DDE,
  Credit Approval) = 90 example rows per scenario

- Each additional scenario variation (e.g. validation checks, missing
  fields) also requires 90 rows

Writing and maintaining these manually was impractical for functional
testers.

**3. Solution --- Comment-Driven Dictionary Expansion**

To address the example table volume problem, a comment-based dictionary
system was introduced. Testers could define variable lists as comments
at the top of a feature file:

> #\${ProductType=\[\"HL\",\"PL\",\"CL\"\]}
>
> #\${ApplicationStage=\[\"DDE\",\"CreditApproval\",\"FDE\"\]}
>
> Feature: Applicant Management

And example tables could use placeholders instead of explicit values:

> Examples:
>
> \| ApplicationStage \| ProductType \|
>
> \| \<ApplicationStage\> \| \<ProductType\> \|

A parser would expand these at runtime into fully populated example
rows. This reduced writing effort significantly.

**3.1 Dictionary Scope Levels**

Dictionaries can be defined at three levels, with narrower scope
overriding broader scope:

**File Level --- Applies to all scenarios in the file**

> #\${ProductType=\[\"HL\",\"PL\"\]}
>
> #\${ApplicationStage=\[\"DDE\",\"CreditApproval\"\]}
>
> Feature: Sourcing Management

**Scenario Level --- Applies to all examples of that scenario only**

> Feature: Sourcing Management
>
> #\${ProductType=\[\"HL\",\"PL\"\]}
>
> #\${ApplicationStage=\[\"DDE\",\"CreditApproval\",\"KYC\"\]}
>
> Scenario Outline: User saves sourcing with mandatory fields
>
> Given \...
>
> When \...
>
> Then \...
>
> Examples:
>
> \| ApplicationStage \| ProductType \|
>
> \| \<ApplicationStage\> \| \<ProductType\> \|

**Example Block Level --- Applies to that specific example block only**

> Scenario Outline: User saves sourcing with mandatory fields
>
> Given \...
>
> When \...
>
> Then \...
>
> #\${ProductType=\[\"Corporate\",\"FAS\"\]}
>
> #\${ApplicationStage=\[\"DDE\",\"CreditApproval\"\]}
>
> Examples:
>
> \| ApplicationStage \| ProductType \|
>
> \| \<ApplicationStage\> \| \<ProductType\> \|

Note: The parser detects dictionary blocks by pattern matching on
\${Key=\[\...\]} regardless of comment prefix style (# \## \#### etc.),
as testers were inconsistent in their formatting.

**4. The Core Architectural Problem --- Stateless Scenarios vs Stateful
CAS**

Even with dictionary expansion solving the volume problem, a deeper
architectural issue emerged. Gherkin scenarios are stateless and
isolated by design. CAS, however, is fundamentally stateful:

- Data entered at Lead Details must survive and be traceable through
  to Disbursal

- Each stage depends on the state created in the previous stage

- Cucumber does not guarantee execution order between scenarios

- Even when filtering applications by stage, there is no guarantee the
  application selected is the same one worked on in a previous
  scenario

The team had built excellent stage-specific screen coverage but had zero
end-to-end flow coverage --- precisely the dimension CAS depends on
most. This is the gap that the existing automation testers would have
identified from day one.

**5. Solution --- Annotation-Driven Ordered Flow**

**5.1 Order.json**

To solve execution ordering, an Order.json file was introduced. It
contains a prioritised list of annotation expressions. Scenarios are
executed top-to-bottom according to which annotation expression they
match first.

> Order: \[
>
> \"@PickApplication\",
>
> \"@OpenApplication\",
>
> \"@Lead and \@OpenApplication\",
>
> \"@Lead and \@AppInfo\",
>
> \"@Lead and \@AppInfo and \@Primary\",
>
> \"@Lead and not \@CoApplicant\",
>
> \"@Lead and \@CoApplicant\",
>
> \"@LoginAcceptance and \@AppInfo\",
>
> \"@LoginAcceptance and not \@MoveToNextStage\",
>
> \"@LoginAcceptance and \@MoveToNextStage\",
>
> \...
>
> \]

**5.2 Ordering Annotations**

Two special file-level annotations control ordering behaviour:

- \@Order --- Scenarios in this file execute in the order defined by
  Order.json. File may cover a partial flow (e.g. LoginAcceptance
  through CreditApproval).

- \@E2EOrder --- Scenarios must cover the complete flow from
  LeadDetails to Disbursal. No stage may be skipped. Typically used
  for sanity flows.

Important rule: A feature file cannot use both comment-driven dictionary
expansion and annotation-driven ordered flow. The two mechanisms are
mutually exclusive.

**5.3 Annotation Scope Levels**

Like dictionaries, annotations follow the same three-level scoping:

**File Level --- Applies to all scenarios and examples in the file**

> \@Order
>
> \@AuthoredBy: anand.singh1
>
> \@ApplicantEpic
>
> \@ICICIBank
>
> \@NotImplemented
>
> \@AppInfo
>
> Feature: Applicant Information

**Scenario Level --- Applies to all examples of that scenario**

> \@PrimaryApplicant
>
> Scenario Outline: Primary applicant should be added
>
> Given \...
>
> When \...
>
> Then \...

**Example Block Level --- Applies to that specific example block**

> \@LeadDetails
>
> Examples:
>
> \| \... \|
>
> \@LoginAcceptance
>
> Examples:
>
> \| \... \|
>
> \@CreditApproval
>
> Examples:
>
> \| \... \|

In the above example, the same scenario executes three times --- once
per stage --- in the order defined by Order.json. Each example block
knows which stage it belongs to.

**5.4 Full Annotated File Example**

> \@Order
>
> \@AuthoredBy: anand.singh1
>
> \@ApplicantEpic
>
> \@ICICIBank
>
> \@GA9.0
>
> \@NotImplemented
>
> \@AppInfo
>
> Feature: Applicant Information
>
> \@PrimaryApplicant
>
> Scenario Outline: Primary applicant should be added
>
> Given \...
>
> When \...
>
> Then \...
>
> \@LeadDetails
>
> Examples:
>
> \| \... \|
>
> \@LoginAcceptance
>
> Examples:
>
> \| \... \|
>
> \@CreditApproval
>
> Examples:
>
> \| \... \|

**6. Solution --- LogicalID for Application Continuity**

Ordered execution solved the sequencing problem, but scenarios were
still stateless. A \@LoginAcceptance scenario could pick up a different
application than the one the \@LeadDetails scenario had just processed.

LogicalID was introduced to bind scenarios to the same application
across the entire flow.

**6.1 How LogicalID Works**

Every ordered scenario must include a LogicalID column in its example
table. The mandatory Given step references this ID:

> Given all prerequisite are performed in previous scenario of
> \"\<ProductType\>\"
>
> logical id \"\<LogicalID\>\" with valid username and password
>
> present in \"LoginDetailsCAS.xlsx\" under \"LoginData\" and 0

When this step executes, it searches across the entire project for all
scenarios sharing the same LogicalID and executes their prerequisites
recursively. This creates a guaranteed execution chain on the exact same
application object.

**6.2 The Binding Together**

- Annotations via Order.json control execution sequence

- LogicalID controls application continuity --- the same application
  is traversed throughout the flow

- Together they simulate stateful E2E flow from within a stateless
  Gherkin framework

**6.3 Real Example**

> Scenario Outline: \<LogicalID\> : Copy Credit Card Application with
> Individual Guarantor
>
> Given all prerequisite are performed in previous scenario of \"Credit
> Card Application\"
>
> logical id \"\<LogicalID\>\" with valid username and password
>
> present in \"LoginDetailsCAS.xlsx\" under \"LoginData\" and 0
>
> And user reads data from the excel file \"copy_application.xlsx\"
> under sheet \"credit\" and row 34
>
> When user navigates to copy application screen
>
> \...
>
> \@CCDE
>
> Examples:
>
> \| LogicalID \| var \| ApplicationStage \|
>
> \| CAS_256008_CCDE \| Application Number \| CCDE \|
>
> \| CAS_256008_CCDE \| CIF Number \| CCDE \|
>
> \@Recommendation
>
> Examples:
>
> \| LogicalID \| var \| ApplicationStage \|
>
> \| CAS_256008_REC \| Application Number \| Recommendation \|
>
> \| CAS_256008_REC \| CIF Number \| Recommendation \|

**7. Known Problems and Technical Debt**

**7.1 Step Inconsistency**

Steps were written by many testers over several years without enforced
language standards. Semantically identical actions exist in the
repository under different wordings:

> Collateral details page should get saved.
>
> Collateral details page is saved.
>
> Collateral detailed page save successfully.

Each of these is mapped to a different Java function in the Selenium
backend, despite performing similar or identical actions. This creates
confusion for new writers about which step to use, and may cause silent
duplication of automation logic.

**7.2 Inconsistent English Quality**

The team relied heavily on interns for scenario writing, with no grammar
or language enforcement. Some steps are grammatically poor or ambiguous,
making them difficult to read and maintain.

**7.3 No Enforced Naming Conventions**

LogicalID naming conventions (e.g. CAS\_\<TicketID\>\_\<Stage\>) were
proposed and adopted by individual contributors but never formally
enforced. The vast majority of the repository does not follow this
convention, making it impossible to trace scenarios back to Jira tickets
without manual investigation.

**7.4 No Consultation with Existing Automation Testers**

The foundational architectural decisions were made without input from
the engineers who understood CAS\'s real operational characteristics.
The stateless vs stateful problem, the ordered flow requirement, and
step reuse discipline were all discovered reactively rather than
designed proactively.

**8. Repository Scale**

**Feature files:** \~1,500

**Scenarios:** \~19,000

**Steps:** \~160,000

**Estimated scenario variants after expansion:** \~80,000 -- 100,000

**Products / LOBs:** 18

**Key stages:** Lead Details, Login Acceptance, KYC, DDE, Credit
Approval, Recommendation, Disbursal

_End of Document_
