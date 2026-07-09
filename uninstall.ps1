#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"
conductor uninstall @args
exit $LASTEXITCODE
