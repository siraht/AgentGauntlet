Feature: Portable Agent Quality Gauntlet setup

  Scenario Outline: setup selects the expected enforcement scope
    Given a target repository with history state "<history>"
    When AQG setup runs in automatic mode
    Then the enforcement scope is "<scope>"
    And a project-local quality launcher is created

    Examples:
      | history | scope   |
      | none    | full    |
      | present | changed |

  Scenario: browser binaries remain opt-in
    Given a target repository with a browser-testable web surface
    When AQG setup runs without the browsers option
    Then Playwright browser installation is not requested

  Scenario: incomplete dependency inventory fails closed
    Given a target repository that declares dependencies without a supported committed lock
    When the supply-chain gate runs
    Then the result is a configuration failure
    And no incomplete inventory is reported as passing
