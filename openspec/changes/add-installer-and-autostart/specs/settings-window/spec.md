## ADDED Requirements

### Requirement: Auto-start is controlled from the settings window

The settings window SHALL let the user turn auto-start off and on, and SHALL show the state that actually applies rather than a remembered preference.

This is the one setting that does not live in `config.toml` — it is a property of the machine, not of the configuration, so it is read from and written to the system rather than the file.

#### Scenario: Seeing the current state

- **WHEN** the user opens the tab containing the auto-start control
- **THEN** it shows whether Ghostwriter will actually start at the next logon

#### Scenario: Turning auto-start on

- **WHEN** the user turns auto-start on
- **THEN** Ghostwriter will start at the next logon
- **AND** the control reflects that

#### Scenario: Elevation is declined

- **WHEN** turning auto-start on needs elevation and the user declines it
- **THEN** the control returns to off
- **AND** the window explains that it could not be enabled

#### Scenario: Auto-start is not available

- **WHEN** Ghostwriter is running from a source checkout, where auto-start cannot be registered
- **THEN** the control says so instead of offering a switch that would not work

#### Scenario: The setting is not written to config.toml

- **WHEN** the user changes auto-start
- **THEN** `config.toml` is not modified
