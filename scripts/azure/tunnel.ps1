param([switch]$WithoutOllama)

$ErrorActionPreference = "Stop"
$arguments = @(
  "-N", "-T",
  "-o", "ExitOnForwardFailure=yes",
  "-o", "ServerAliveInterval=30",
  "-L", "3000:127.0.0.1:3000",
  "-L", "8080:127.0.0.1:8080",
  "-L", "18000:127.0.0.1:18000",
  "-L", "9001:127.0.0.1:9001"
)

if (-not $WithoutOllama) {
  try {
    Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3 | Out-Null
  } catch {
    throw "Laptop Ollama is not reachable on 127.0.0.1:11434. Start it or use -WithoutOllama."
  }
  $arguments += @("-R", "172.17.0.1:11434:127.0.0.1:11434")
}

$arguments += "orbital-vm"
& ssh @arguments
exit $LASTEXITCODE
