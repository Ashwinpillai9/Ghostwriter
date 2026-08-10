# Launches Ghostwriter. Use run-hidden.vbs instead if you want no console window.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
& "$PSScriptRoot\.venv\Scripts\python.exe" -m ghostwriter.app @args
