<#
.SYNOPSIS
    Installs, updates or removes Ghostwriter.

.DESCRIPTION
    Fetches the latest release, unpacks it to %LOCALAPPDATA%\Ghostwriter, adds a Start Menu
    shortcut and registers Ghostwriter to start when you log in.

    Nothing here needs administrator rights except registering auto-start, which asks for them
    at the moment it needs them. Your config.toml and downloaded models live outside the
    program directory, so an update never touches them.

.EXAMPLE
    irm https://raw.githubusercontent.com/Ashwinpillai9/Ghostwriter/main/install.ps1 | iex

.EXAMPLE
    .\install.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [switch]$Uninstall,
    [switch]$Purge,          # with -Uninstall: also remove config and downloaded models
    [switch]$NoAutoStart,
    [string]$Repo = "Ashwinpillai9/Ghostwriter"
)

$ErrorActionPreference = "Stop"

$AppName    = "Ghostwriter"
$InstallDir = Join-Path $env:LOCALAPPDATA $AppName
$DataDir    = Join-Path $env:APPDATA      $AppName
$TaskName   = $AppName
$ExePath    = Join-Path $InstallDir "$AppName.exe"
$Shortcut   = Join-Path ([Environment]::GetFolderPath("Programs")) "$AppName.lnk"

function Write-Step($message) { Write-Host "==> $message" -ForegroundColor Cyan }
function Write-Note($message) { Write-Host "    $message" -ForegroundColor DarkGray }
function Write-Warn($message) { Write-Host "    $message" -ForegroundColor Yellow }

function Stop-Ghostwriter {
    # Its files cannot be replaced while it holds them open.
    Get-Process -Name $AppName -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Note "Stopping the running copy (pid $($_.Id))"
        $_ | Stop-Process -Force
    }
    Start-Sleep -Milliseconds 600
}

function Remove-AutoStart {
    schtasks /query /tn $TaskName *> $null
    if ($LASTEXITCODE -eq 0) {
        schtasks /delete /tn $TaskName /f *> $null
        if ($LASTEXITCODE -eq 0) { Write-Note "Removed the logon task" }
        else { Write-Warn "Could not remove the logon task; remove '$TaskName' in Task Scheduler" }
    }
}

function Add-AutoStart {
    # 'highest' is the point of using a scheduled task rather than a Run key: Windows does not
    # deliver input to a lower-privilege process, so without it the hotkeys are dead whenever an
    # elevated window has focus.
    Write-Step "Registering auto-start"
    schtasks /create /tn $TaskName /tr "`"$ExePath`"" /sc onlogon /rl highest /f *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Note "Ghostwriter will start when you log in"
    } else {
        Write-Warn "Could not register auto-start (administrator permission is needed)."
        Write-Warn "Turn it on later from Settings, or re-run this script as administrator."
    }
}

# --- uninstall ---------------------------------------------------------------

if ($Uninstall) {
    Write-Step "Removing $AppName"
    Stop-Ghostwriter
    Remove-AutoStart

    if (Test-Path $Shortcut)   { Remove-Item $Shortcut -Force }
    if (Test-Path $InstallDir) { Remove-Item $InstallDir -Recurse -Force }
    Write-Note "Removed the program files"

    if ($Purge) {
        if (Test-Path $DataDir) { Remove-Item $DataDir -Recurse -Force }
        $cache = Join-Path $env:USERPROFILE ".cache\huggingface"
        if (Test-Path $cache) { Remove-Item $cache -Recurse -Force }
        Write-Note "Removed your settings and the downloaded models"
    } else {
        # Never delete the user's own things without being asked.
        Write-Host ""
        Write-Note "Your settings and downloaded models were kept:"
        Write-Note "  settings : $DataDir"
        Write-Note "  models   : $(Join-Path $env:USERPROFILE '.cache\huggingface')"
        Write-Note "Re-run with -Uninstall -Purge to remove those too."
    }

    Write-Host ""
    Write-Host "$AppName removed." -ForegroundColor Green
    return
}

# --- install / update --------------------------------------------------------

$Existing = Test-Path $ExePath
Write-Step $(if ($Existing) { "Updating $AppName" } else { "Installing $AppName" })

Write-Step "Finding the latest release"
try {
    $release = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest" `
        -Headers @{ "User-Agent" = "ghostwriter-installer" }
} catch {
    throw "Could not reach GitHub to find a release: $($_.Exception.Message)"
}

$asset = $release.assets | Where-Object { $_.name -like "*windows*.zip" } | Select-Object -First 1
if (-not $asset) { $asset = $release.assets | Where-Object { $_.name -like "*.zip" } | Select-Object -First 1 }
if (-not $asset) { throw "That release has no downloadable archive." }
Write-Note "$($release.tag_name) — $($asset.name) ($([math]::Round($asset.size / 1MB)) MB)"

# Download and unpack somewhere temporary first: a failed download must leave a working
# installation alone rather than half-replacing it.
$staging = Join-Path ([System.IO.Path]::GetTempPath()) "ghostwriter-install-$(Get-Random)"
New-Item -ItemType Directory -Path $staging -Force | Out-Null
$archive = Join-Path $staging $asset.name

try {
    Write-Step "Downloading"
    $progress = $ProgressPreference
    $ProgressPreference = "SilentlyContinue"   # the built-in bar makes this many times slower
    Invoke-WebRequest $asset.browser_download_url -OutFile $archive
    $ProgressPreference = $progress

    Write-Step "Unpacking"
    Expand-Archive -Path $archive -DestinationPath $staging -Force

    $payload = Get-ChildItem $staging -Directory |
        Where-Object { Test-Path (Join-Path $_.FullName "$AppName.exe") } |
        Select-Object -First 1
    if (-not $payload) {
        if (Test-Path (Join-Path $staging "$AppName.exe")) { $payload = Get-Item $staging }
        else { throw "The archive does not contain $AppName.exe." }
    }

    Stop-Ghostwriter

    Write-Step "Installing to $InstallDir"
    if (Test-Path $InstallDir) { Remove-Item $InstallDir -Recurse -Force }
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    Copy-Item (Join-Path $payload.FullName "*") $InstallDir -Recurse -Force
} finally {
    if (Test-Path $staging) { Remove-Item $staging -Recurse -Force -ErrorAction SilentlyContinue }
}

if (-not (Test-Path $ExePath)) { throw "Install finished but $AppName.exe is not there." }

Write-Step "Adding a Start Menu shortcut"
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($Shortcut)
$link.TargetPath = $ExePath
$link.WorkingDirectory = $InstallDir
$link.Description = "Local push-to-talk dictation"
$link.Save()

if (-not $NoAutoStart) { Add-AutoStart } else { Write-Note "Skipped auto-start (-NoAutoStart)" }

Write-Host ""
Write-Host "$AppName $($release.tag_name) installed." -ForegroundColor Green
Write-Host ""
Write-Note "Double-tap Right Ctrl and hold it to dictate."
Write-Note "Settings and Quit live in the tray icon."
if (-not $Existing) {
    Write-Host ""
    Write-Warn "First run downloads the speech model (~1.6 GB), and GPU support if you have an"
    Write-Warn "NVIDIA card. The pill above your taskbar shows progress. It happens once."
}

Write-Step "Starting $AppName"
Start-Process $ExePath -WorkingDirectory $InstallDir
