## Purpose

Getting Ghostwriter onto a Windows machine, keeping it current, and removing it again — without requiring Python, a repository checkout, or a terminal afterwards, and without shipping gigabytes that most machines cannot use.

## ADDED Requirements

### Requirement: Installing in one command

Ghostwriter SHALL be installable with a single command that needs no prior setup, and SHALL NOT require Python, a repository checkout, or administrator rights to install.

#### Scenario: Installing on a clean machine

- **WHEN** the user runs the install command on a machine with no Python and no Ghostwriter
- **THEN** Ghostwriter is installed and can be launched
- **AND** no administrator prompt was required to unpack it

#### Scenario: Installing while a copy is already running

- **WHEN** the user installs over a version that is currently running
- **THEN** the running copy is stopped before its files are replaced
- **AND** the newly installed version is running when the install finishes

#### Scenario: The download fails part way

- **WHEN** the download is interrupted
- **THEN** the installer reports the failure
- **AND** any previously installed version is left working

### Requirement: The download excludes what most machines cannot use

The installed download SHALL NOT include the NVIDIA CUDA runtime, which is useful only on machines with an NVIDIA GPU and is several times the size of everything else combined.

#### Scenario: Size of the download

- **WHEN** the user installs Ghostwriter
- **THEN** the download does not contain the CUDA runtime
- **AND** it does not contain the speech model

#### Scenario: A machine without an NVIDIA GPU

- **WHEN** Ghostwriter is installed on a machine with no NVIDIA GPU
- **THEN** dictation works, transcribing on the processor
- **AND** no CUDA runtime is ever downloaded

### Requirement: First run fetches what the machine can use

On first run Ghostwriter SHALL obtain the pieces it did not ship with, choosing them by what the machine can actually use, and SHALL report progress rather than appearing to hang.

#### Scenario: First run on a machine with an NVIDIA GPU

- **WHEN** Ghostwriter starts for the first time on a machine with an NVIDIA GPU
- **THEN** it fetches the CUDA runtime and the speech model
- **AND** progress is shown while it does
- **AND** dictation works on the GPU once it finishes

#### Scenario: First run without an NVIDIA GPU

- **WHEN** Ghostwriter starts for the first time on a machine with no NVIDIA GPU
- **THEN** it fetches only the speech model
- **AND** dictation works on the processor once it finishes

#### Scenario: No internet on first run

- **WHEN** the machine has no internet connection on first run
- **THEN** Ghostwriter reports what it could not fetch and stays running
- **AND** it retries the next time it starts, rather than requiring reinstallation

#### Scenario: Subsequent runs

- **WHEN** Ghostwriter starts again after a successful first run
- **THEN** it does not download anything and starts without delay

### Requirement: Updating in place

Re-running the install command SHALL update an existing installation, preserving the user's configuration.

#### Scenario: Updating to a newer version

- **WHEN** the user runs the install command on a machine that already has Ghostwriter
- **THEN** the program files are replaced with the newer version
- **AND** `config.toml` and its comments are left exactly as they were
- **AND** already-downloaded models are not fetched again

#### Scenario: Auto-start survives an update

- **WHEN** an installation with auto-start enabled is updated
- **THEN** Ghostwriter still starts at logon afterwards

### Requirement: Uninstalling

Ghostwriter SHALL be removable by a single command that leaves nothing running and nothing scheduled.

#### Scenario: Uninstalling

- **WHEN** the user runs the uninstall command
- **THEN** the running copy is stopped
- **AND** the program files are removed
- **AND** it no longer starts at logon

#### Scenario: Personal data is kept unless asked for

- **WHEN** the user uninstalls without asking for a complete removal
- **THEN** `config.toml` and the downloaded models are left in place
- **AND** the user is told where they are and how to remove them

#### Scenario: Complete removal

- **WHEN** the user asks for a complete removal
- **THEN** the configuration and downloaded models are removed as well

### Requirement: One executable serves both windows

The installed build SHALL provide the settings window without requiring a Python interpreter, since a frozen build cannot run `python -m`.

#### Scenario: Opening settings from an installed copy

- **WHEN** the user opens Settings from the tray of an installed copy
- **THEN** the settings window opens
- **AND** it behaves the same as it does when running from source
