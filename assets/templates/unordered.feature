@Epic-<EpicName>
@AuthoredBy-<AuthorName>
@ImplementedBy-<ImplementedBy>
@ReviewedBy-<ReviewedBy>
@<PrimaryModuleTag>
@<OptionalFlowTag>
@<JIRA_ID>


# Notes:
# 1. UnOrdered flow is mandatory user input. Never infer it.
# 2. UnOrdered files must use dictionary-style comment expansion.
# 3. Every scenario must carry Dictionaries variables in Examples.
# 4. Repo style should preserve Given/And setup chain.
# 5. Assertion block must be:
#    Then
#    or Then + And
#    never more than 1 And after Then.
# 6. Sample steps are below, There Can be Varying number of And in Given and When Depending on scenario to make sense




# file-level dictionaries
#${ProductType:["HL","PL"]}
#${ApplicationStage:["Lead Details","DDE","Credit Approval"]}
#${ApplicantType:["indiv","nonindiv"]}   ## If needed

Feature: <Feature Title>

    Background:
        Given user is on CAS Login Page
        And user logged in CAS with valid username and password present in "LoginDetailsCAS.xlsx" under "LoginData" and 0

    Scenario Outline: <Scenario Title>
        Given <setup step from repo>
        And <setup step from repo>
        When <action step from repo>
        And <optional continuation action from repo>
        Then <assertion step from repo>
        And <optional final assertion step from repo>
        # Optional scenario/example-level dictionaries may be added only when needed

        @<ExampleBlockTag1>
        Examples:
            | ProductType   | ApplicationStage   | StepVariable      | ifStepHasVariables2      |
            | <ProductType> | <ApplicationStage> | StepVariableValue | ifStepHasVariables2Value |

        @<OptionalSecondExampleBlockTag>
        Examples:
            | ProductType   | ApplicationStage   | StepVariable      | ifStepHasVariables2      |
            | <ProductType> | <ApplicationStage> | StepVariableValue | ifStepHasVariables2Value |

    Scenario Outline: <Negative or Edge Scenario Title>
        Given <setup step from repo>
        And <setup step from repo>
        When <action step from repo>
        Then <assertion step from repo>
        And <optional final assertion step from repo>

        @<ExampleBlockTag>
        Examples:
            | ProductType   | ApplicationStage   | StepVariable      | ifStepHasVariables2      |
            | <ProductType> | <ApplicationStage> | StepVariableValue | ifStepHasVariables2Value |
