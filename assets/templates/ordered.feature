@Epic-<EpicName>
@AuthoredBy-<AuthorName>
@ImplementedBy-<ImplementedBy>
@ReviewedBy-<ReviewedBy>
@Order
@<PrimaryModuleTag>
@<OptionalReleaseTag>
@<JIRA_ID>
Feature: <Feature Title>

    # Notes:
    # 1. Ordered flow is mandatory user input. Never infer it.
    # 2. Ordered files must NOT use dictionary-style comment expansion.
    # 3. Every scenario must carry LogicalID in title and Examples.
    # 4. Repo style should preserve Given/And setup chain.
    # 5. Assertion block must be:
    #    Then
    #    or Then + And
    #    never more than 1 And after Then.
    # 6. Sample steps are below, There Can be Varying number of And in Given and When Depending on scenario to make sense

    #########################################################################################################
    ###### BUSINESS CONTEXT
    ###### --------------------------------------------------------------------------------------------------
    ###### <JIRA CONTEXT>
    ######   - <Basic Summary line 1>
    ######   - <Basic Summary line 2>
    ######   - <Optional Basic Summary line 3>
    #########################################################################################################

    Scenario Outline: For App with [ <LogicalID> ] <Scenario Title>
        Given all prerequisite are performed in previous scenario of "<ProductType>" logical id "<LogicalID>"
        And <needed setup step from repo>
        And <more optional setup steps if needed setup step from repo>
        When <action step from repo>
        And <optional continuation action from repo needed for Then>
        And <optional continuation action from repo  needed for Then>
        Then <assertion step from repo>
        And <optional final assertion step from repo>
        Examples:
            | LogicalID   | ProductType   | StepVariable      | ifStepHasVariables2      |
            | <LogicalID> | <ProductType> | StepVariableValue | ifStepHasVariables2Value |

    Scenario Outline: <Next Scenario Title> LogicalID <LogicalID>
        Given all prerequisite are performed in previous scenario of "<ProductType>" logical id "<LogicalID>"
        And <setup/navigation step from repo>
        And <setup/navigation step from repo>
        When <action step from repo>
        Then <assertion step from repo>
        And <optional final assertion step from repo>
        Examples:
            | LogicalID   | ProductType   | StepVariable      | ifStepHasVariables2      |
            | <LogicalID> | <ProductType> | StepVariableValue | ifStepHasVariables2Value |