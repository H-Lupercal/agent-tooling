#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
python -m conductor.install --uninstall @args
exit $LASTEXITCODE
