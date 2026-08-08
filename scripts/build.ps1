param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $BuildArgs
)

python "$PSScriptRoot\build.py" @BuildArgs
exit $LASTEXITCODE
