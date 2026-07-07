#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
python -m conductor.install @args
exit $LASTEXITCODE
