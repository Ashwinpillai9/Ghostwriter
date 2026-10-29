## Purpose

Running Ghostwriter when the user logs in, at a privilege level where its global hotkeys actually work — including over elevated windows, which a normally-launched copy cannot reach.

## ADDED Requirements

### Requirement: Starting at logon

Ghostwriter SHALL start automatically when the user logs in, and SHALL be enabled by default on a new installation.

#### Scenario: Logging in after installing

- **WHEN** the user logs in to Windows after installing Ghostwriter
- **THEN** Ghostwriter is running, with its tray icon present
- **AND** it started without a console window or any visible prompt

#### Scenario: A fresh installation

- **WHEN** Ghostwriter is installed
- **THEN** auto-start is enabled without the user having to ask for it

### Requirement: Hotkeys work over elevated windows

Auto-started Ghostwriter SHALL run with sufficient privilege that its hotkeys work regardless of what window has focus.

Windows blocks input from a lower-privilege process, so a normally-launched copy cannot see keystrokes while an elevated window is focused — a limitation the troubleshooting notes currently describe as unavoidable.

#### Scenario: Dictating into an elevated window

- **WHEN** an administrator terminal has focus
- **AND** the user presses the dictation hotkey
- **THEN** recording starts, exactly as it would over any other window

#### Scenario: Starting at logon is silent

- **WHEN** Ghostwriter starts at logon with elevated privilege
- **THEN** no consent prompt appears

### Requirement: Auto-start can be turned off and on

The user SHALL be able to change whether Ghostwriter starts at logon, without reinstalling.

#### Scenario: Turning it off

- **WHEN** the user turns auto-start off
- **THEN** Ghostwriter does not start at the next logon
- **AND** the running copy keeps running

#### Scenario: Turning it back on

- **WHEN** the user turns auto-start on again
- **THEN** Ghostwriter starts at the next logon

#### Scenario: Consent is asked for at the moment it is needed

- **WHEN** turning auto-start on requires elevation
- **THEN** the user is asked for it then, in response to their own action
- **AND** declining leaves auto-start off rather than in an unclear state

### Requirement: The reported state matches reality

Ghostwriter SHALL report whether it will start at logon based on the actual system state, not on a remembered preference, so that a change made outside Ghostwriter is not contradicted.

#### Scenario: Auto-start removed outside Ghostwriter

- **WHEN** the user removes Ghostwriter's logon entry through Windows' own tools
- **AND** then opens Ghostwriter's settings
- **THEN** auto-start is shown as off

#### Scenario: Reporting on a machine where it was never enabled

- **WHEN** auto-start has never been enabled
- **THEN** it is shown as off, and no error is reported

### Requirement: Auto-start failure is not fatal

A failure to register or query auto-start SHALL NOT prevent Ghostwriter from running.

#### Scenario: Registration is refused

- **WHEN** registering auto-start fails, for example because elevation was declined
- **THEN** the user is told it could not be enabled
- **AND** Ghostwriter continues to run normally

#### Scenario: Running from source

- **WHEN** Ghostwriter is run from a source checkout rather than an installation
- **THEN** it starts and works normally whether or not auto-start is available
