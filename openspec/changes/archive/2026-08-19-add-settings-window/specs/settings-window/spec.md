## Purpose

A visual editor for Ghostwriter's configuration. It presents every setting in labelled groups, writes changes back to `config.toml` without destroying the comments that document it, offers live microphone and appearance feedback that a text file cannot, and states plainly which changes take effect immediately and which need a restart.

## ADDED Requirements

### Requirement: Opening the settings window

The settings window SHALL be reachable from the tray menu and SHALL run as a separate process from the dictation app, so that a failure in the settings UI cannot interrupt dictation.

#### Scenario: Opening from the tray

- **WHEN** the user selects "Settings" from the tray menu
- **THEN** the settings window opens showing the current values from `config.toml`

#### Scenario: Settings window is already open

- **WHEN** the user selects "Settings" while the window is already open
- **THEN** the existing window is brought to the front rather than a second one being opened

#### Scenario: The settings process crashes

- **WHEN** the settings process terminates unexpectedly
- **THEN** dictation, hotkeys and the overlay continue working unaffected

### Requirement: Changes reach the running application

The settings window SHALL apply a change by writing `config.toml`, and SHALL NOT require any other channel to the running application.

#### Scenario: Changing a live-applicable setting

- **WHEN** the user changes the accent colour and the change is committed
- **THEN** `config.toml` is updated
- **AND** the running application picks the change up within about a second, without a restart

#### Scenario: The dictation app is not running

- **WHEN** the user changes a setting while Ghostwriter itself is not running
- **THEN** the change is still written to `config.toml` and takes effect the next time the app starts

### Requirement: Restart-required settings are named, not hidden

The settings window SHALL identify settings that cannot take effect until the application restarts, and SHALL tell the user which ones are pending.

#### Scenario: Selecting a different dictation model

- **WHEN** the user selects a different `model.name`
- **THEN** the choice is written to `config.toml`
- **AND** the window shows that the dictation model needs a restart to take effect
- **AND** the currently loaded model keeps being used until the application restarts

#### Scenario: Changing only live-applicable settings

- **WHEN** the user changes settings that all apply live
- **THEN** no restart notice is shown

### Requirement: Config file remains readable after editing

Writing a setting SHALL preserve the comments, ordering and formatting of `config.toml`, and SHALL leave untouched keys byte-identical.

#### Scenario: Editing one value

- **WHEN** the settings window writes a single changed value
- **THEN** every comment in `config.toml` is preserved
- **AND** the ordering of sections and keys is unchanged
- **AND** no key that the user did not change is rewritten

#### Scenario: Setting a key absent from the file

- **WHEN** the user changes a setting whose key is not present in `config.toml`
- **THEN** the key is added to its correct section, creating the section if needed

### Requirement: Writes do not corrupt the config

A write SHALL be atomic, so that an interrupted save cannot leave `config.toml` truncated or half-written.

#### Scenario: A save is interrupted

- **WHEN** the process is terminated during a write
- **THEN** `config.toml` is either the previous complete version or the new complete version, never a partial one

#### Scenario: Rapid consecutive edits

- **WHEN** the user drags a slider through many intermediate values
- **THEN** the file is written on commit rather than on every intermediate value, so the running application reloads once rather than continuously

### Requirement: External edits are not clobbered

The settings window SHALL reflect changes made to `config.toml` by other editors while it is open.

#### Scenario: The file changes underneath an open window

- **WHEN** `config.toml` is modified by another program while the settings window is open
- **THEN** the window reflects the new values rather than overwriting them with what it had loaded

### Requirement: Hotkeys are captured by pressing them

The Keys tab SHALL let the user set a binding by pressing the intended key combination, and SHALL distinguish left from right modifier keys.

#### Scenario: Recording a binding

- **WHEN** the user activates the capture control and presses a key combination
- **THEN** that combination is shown and written as the binding

#### Scenario: Pressing a side-specific modifier

- **WHEN** the user presses the right-hand Ctrl key during capture
- **THEN** the binding is recorded as right Ctrl specifically, not as a generic Ctrl

#### Scenario: Abandoning a capture

- **WHEN** the user starts capturing and then cancels
- **THEN** the previous binding is left unchanged

### Requirement: The wake word can be tested without dictating

The Wake word tab SHALL let the user check whether their phrase is recognised, reporting the match against the configured threshold.

#### Scenario: Testing a phrase that matches

- **WHEN** the user runs the wake-word test and says the configured phrase
- **THEN** the window reports that the phrase was heard and how closely it matched

#### Scenario: Testing a phrase that does not match

- **WHEN** the user runs the test and says something unlike the phrase
- **THEN** the window reports what it heard and that it did not match

#### Scenario: The test does not disturb dictation

- **WHEN** the wake-word test is running
- **THEN** the running application's own wake-word listener is not left broken when the test finishes

### Requirement: Model availability is visible before selection

The Model tab SHALL show, for each selectable model, its approximate size and whether it is already downloaded.

#### Scenario: Reviewing models

- **WHEN** the user opens the Model tab
- **THEN** each model is listed with its size and whether it is on disk

#### Scenario: Choosing a model that is not downloaded

- **WHEN** the user selects a model that is not on disk
- **THEN** the window makes clear it will be downloaded on next use, and does not download it in the background

### Requirement: Microphone behaviour is observable

The Mic tab SHALL show a live input level for the selected device, and SHALL offer a measurement of the room that suggests threshold values.

#### Scenario: Watching the input level

- **WHEN** the user opens the Mic tab and speaks
- **THEN** a level meter responds to their voice

#### Scenario: Switching input device

- **WHEN** the user selects a different input device
- **THEN** the level meter follows the newly selected device

#### Scenario: Measuring the room

- **WHEN** the user runs the room measurement
- **THEN** the window reports the background noise level and speaking level
- **AND** suggests threshold values suited to that room, which the user can accept or decline

#### Scenario: The meter releases the microphone

- **WHEN** the user leaves the Mic tab or closes the window
- **THEN** the settings process stops capturing audio

### Requirement: Appearance changes are previewed

The Look tab SHALL show a preview of the status pill that matches how the pill actually renders.

#### Scenario: Changing the accent colour

- **WHEN** the user picks a different accent colour
- **THEN** the preview updates to that colour
- **AND** the preview matches what the real overlay pill will look like

### Requirement: Invalid input is rejected before it is written

The settings window SHALL constrain values to what the application accepts, so that editing through the window cannot produce a config the application will warn about or ignore.

#### Scenario: A value outside its permitted range

- **WHEN** the user attempts to set a numeric value outside the range the application accepts
- **THEN** the value is constrained to the permitted range and the file is not written with an invalid value

#### Scenario: An unparseable colour

- **WHEN** the user enters a colour that is not a valid hex colour
- **THEN** the window rejects it and keeps the previous colour
