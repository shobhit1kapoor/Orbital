param([Parameter(ValueFromRemainingArguments = $true)][string[]]$RemoteArguments)
& ssh orbital-vm @RemoteArguments
exit $LASTEXITCODE
