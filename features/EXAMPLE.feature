Feature: Example behavior

  Scenario Outline: Valid and invalid requests produce explicit outcomes
    Given the system is in a known state
    When a request with value <value> is submitted
    Then the outcome is <outcome>

    Examples:
      | value   | outcome  |
      | valid   | accepted |
      | invalid | rejected |
