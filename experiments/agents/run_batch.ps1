# Runs one experiment batch: starts the tokenprof proxy in front of Gemini, runs every
# framework for N repetitions with the given tool style, then stops the proxy.
#   .\run_batch.ps1 -Style full -Name baseline
param(
    [Parameter(Mandatory)] [ValidateSet("full", "compact")] [string] $Style,
    [Parameter(Mandatory)] [string] $Name,
    [string[]] $Frameworks = @("smolagents", "openai_agents"),
    [int] $Reps = 2,
    [string] $Model = "gemini-3.5-flash-lite",
    # Needed for LangGraph: langchain-openai drops Gemini's thought signatures.
    [switch] $RestoreSignatures
)
$ErrorActionPreference = "Stop"
$exp = $PSScriptRoot
$repo = Resolve-Path "$exp\..\.."
$results = "$repo\docs\results"
$date = Get-Date -Format "yyyy-MM-dd"
$trace = "$results\$date-exp-$Name.jsonl"
$answers = "$results\$date-exp-$Name-answers.jsonl"

$proxyArgs = @("proxy", "--upstream", "https://generativelanguage.googleapis.com/v1beta/openai", "--out", $trace, "--port", "8788")
if ($RestoreSignatures) { $proxyArgs += "--restore-thought-signatures" }
$proxy = Start-Process -WindowStyle Hidden -PassThru -FilePath "$repo\.venv\Scripts\tokenprof.exe" -ArgumentList $proxyArgs
Start-Sleep -Seconds 3
$env:PYTHONIOENCODING = "utf-8"
try {
    foreach ($rep in 1..$Reps) {
        foreach ($fw in $Frameworks) {
            & "$exp\.venv\Scripts\python.exe" "$exp\run.py" --framework $fw --style $Style --rep $rep --model $Model --results $answers
        }
    }
}
finally {
    Stop-Process -Id $proxy.Id
}
Write-Output "trace: $trace"
Write-Output "answers: $answers"
