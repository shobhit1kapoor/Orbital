$ErrorActionPreference = "Stop"
$azCommand = Get-Command az -ErrorAction SilentlyContinue
$az = if ($azCommand) { $azCommand.Source } else { "$env:ProgramFiles\Microsoft SDKs\Azure\CLI2\wbin\az.cmd" }
if (-not (Test-Path $az)) { throw "Azure CLI is not installed." }
& $az account set --subscription "Azure for Students"
& $az vm deallocate --resource-group orbital-sigma-rg --name orbital-sigma-vm --output none
if ($LASTEXITCODE -ne 0) { throw "Failed to deallocate orbital-sigma-vm." }
$state = & $az vm get-instance-view --resource-group orbital-sigma-rg `
  --name orbital-sigma-vm `
  --query "instanceView.statuses[?starts_with(code, 'PowerState/')].code | [0]" `
  --output tsv
if ($state -ne "PowerState/deallocated") {
  throw "Azure returned '$state' after the deallocation request."
}
Write-Output "orbital-sigma-vm is deallocated; compute billing has stopped."
