$ErrorActionPreference = "Stop"
$azCommand = Get-Command az -ErrorAction SilentlyContinue
$az = if ($azCommand) { $azCommand.Source } else { "$env:ProgramFiles\Microsoft SDKs\Azure\CLI2\wbin\az.cmd" }
if (-not (Test-Path $az)) { throw "Azure CLI is not installed." }
& $az account set --subscription "Azure for Students"
& $az vm start --resource-group orbital-sigma-rg --name orbital-sigma-vm --output none
if ($LASTEXITCODE -ne 0) { throw "Failed to start orbital-sigma-vm." }
& $az vm wait --resource-group orbital-sigma-rg --name orbital-sigma-vm --updated
& $az vm get-instance-view --resource-group orbital-sigma-rg --name orbital-sigma-vm `
  --query "instanceView.statuses[?starts_with(code, 'PowerState/')].displayStatus | [0]" `
  --output tsv
