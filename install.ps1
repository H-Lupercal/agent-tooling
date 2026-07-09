#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"
conductor install @args
exit $LASTEXITCODE
