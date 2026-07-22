param([switch]$ConfirmDelete)

$ErrorActionPreference = "Stop"
if (-not $ConfirmDelete) {
  throw "Deletion is irreversible. Re-run with -ConfirmDelete to delete orbital-sigma-rg."
}

$azCommand = Get-Command az -ErrorAction SilentlyContinue
$az = if ($azCommand) { $azCommand.Source } else { "$env:ProgramFiles\Microsoft SDKs\Azure\CLI2\wbin\az.cmd" }
if (-not (Test-Path $az)) { throw "Azure CLI is not installed." }
& $az account set --subscription "Azure for Students"
& $az group delete --name orbital-sigma-rg --yes --no-wait
if ($LASTEXITCODE -ne 0) { throw "Failed to submit resource-group deletion." }
Write-Output "Deletion submitted for orbital-sigma-rg, including disk and public IP."
