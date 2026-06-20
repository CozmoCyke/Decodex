param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$Args
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$candidates = @($env:DECODEX_PYTHON, $env:PYTHON, $env:PYTHON3, "python", "python3") | Where-Object { $_ }

$python = $null
foreach ($candidate in $candidates) {
  if (Test-Path -LiteralPath $candidate) {
    $python = $candidate
    break
  }
  $resolved = Get-Command $candidate -ErrorAction SilentlyContinue
  if ($resolved) {
    $python = $resolved.Source
    break
  }
}

if (-not $python) {
  throw "No usable Python interpreter found."
}

& $python "$root\tools\decodex.py" @Args
exit $LASTEXITCODE
