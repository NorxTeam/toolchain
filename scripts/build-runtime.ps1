param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $BuildArgs
)

python "$PSScriptRoot\build-runtime.py" @BuildArgs
exit $LASTEXITCODE
