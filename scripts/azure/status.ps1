$ErrorActionPreference = "Stop"
$azCommand = Get-Command az -ErrorAction SilentlyContinue
$az = if ($azCommand) { $azCommand.Source } else { "$env:ProgramFiles\Microsoft SDKs\Azure\CLI2\wbin\az.cmd" }
if (-not (Test-Path $az)) { throw "Azure CLI is not installed." }
& $az account set --subscription "Azure for Students"
$state = & $az vm get-instance-view --resource-group orbital-sigma-rg `
  --name orbital-sigma-vm `
  --query "instanceView.statuses[?starts_with(code, 'PowerState/')].displayStatus | [0]" `
  --output tsv
$ip = & $az network public-ip show --resource-group orbital-sigma-rg `
  --name orbital-sigma-pip --query ipAddress --output tsv
[pscustomobject]@{ VM = "orbital-sigma-vm"; State = $state; PublicIP = $ip }
