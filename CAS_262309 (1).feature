@Epic-CAS
@AuthoredBy-CASForge
@ImplementedBy-CASForge
@ReviewedBy-CASForge
@Order
@AppInfo
@Generated
@CAS-262309

Feature: GA 9.0 - Add on Applicant - Dynamic form Placeholder

    # CASForge notice: some steps were not found in repository and were generated.
    # [NEW_STEP_NOT_IN_REPO] Then "<Field_Name>" field should be visible in raise manual deviation modal on Credit Approval
    # [NEW_STEP_NOT_IN_REPO] And user opens an application of "<ProductType>" product type as "<ApplicantType>" applicant at "<ApplicationStage>" for "<Category>" with "<Key>" from application grid
    # [NEW_STEP_NOT_IN_REPO] And user reads data from the excel file "<PersonalInfoWB>" under sheet "<PersonalInfo_home>" and row <PersonalInfo_home_rowNum>
    # [NEW_STEP_NOT_IN_REPO] And user creates new application for "<ProductType>"
    # [NEW_STEP_NOT_IN_REPO] Then "<Fields>" should be display at the top of personal information screen

    #########################################################################################################
    ###### Core Flow Coverage
    #########################################################################################################

    Scenario Outline: For App with [ <LogicalID> ] Display CDDE, recommendation, credit approval and stage
        Given all prerequisite are performed in previous scenario of "<ProductType>" logical id "<LogicalID>"
        And user is on CAS Login Page
        And user logged in CAS with valid username and password present in "LoginDetailsCAS.xlsx" under "LoginData" and 0
        When user opens an application of "credit approval" stage variant from "CREDIT_APPROVAL" grid
        And open raise manual deviation modal on credit approval
        Then "<Field_Name>" field should be visible in raise manual deviation modal on Credit Approval

        Examples:
            | LogicalID | ProductType | Field_Name |
            | CAS_262309_001 | <ProductType> | <Field_Name> |

    Scenario Outline: For App with [ <LogicalID> ] Display dynamic form placeholder
        Given all prerequisite are performed in previous scenario of "<ProductType>" logical id "<LogicalID>"
        And user is on CAS Login Page
        And dynamic Form is attached in Share Purchase Tab using placeholder "CAS_CUSTOM_FIELDS_SCREEN_SHARE_PURCHASE" from Dynamic form Screen Mapping
        And user logged in CAS with valid username and password present in "LoginDetailsCAS.xlsx" under "LoginData" and 0
        And user reads data from the excel file "shares.xlsx" under sheet "background" and row 0
        And user opens an application of "<ProductType>" product type as "<ApplicantType>" applicant at "<ApplicationStage>" for "<Category>" with "<Key>" from application grid
        When user is on Share Purchase Tab
        Then dynamic form should be visible in view only mode

        Examples:
            | LogicalID | ProductType | ApplicantType | Category | Key |
            | CAS_262309_002 | <ProductType> | <ApplicantType> | <Category> | <Key> |

    Scenario Outline: For App with [ <LogicalID> ] Display personal information screen
        Given all prerequisite are performed in previous scenario of "<ProductType>" logical id "<LogicalID>"
        And user is on CAS Login Page
        And user logged in CAS with valid username and password present in "LoginDetailsCAS.xlsx" under "LoginData" and 0
        And user reads data from the excel file "<PersonalInfoWB>" under sheet "<PersonalInfo_home>" and row <PersonalInfo_home_rowNum>
        And user creates new application for "<ProductType>"
        And user selects Expanded Mode in applicant information
        When user fills home page of personal information
        And user clicks on proceed to next
        Then "<Fields>" should be display at the top of personal information screen

        Examples:
            | LogicalID | ProductType | PersonalInfoWB | PersonalInfo_home | PersonalInfo_home_rowNum | Fields |
            | CAS_262309_003 | <ProductType> | <PersonalInfoWB> | <PersonalInfo_home> | <PersonalInfo_home_rowNum> | <Fields> |