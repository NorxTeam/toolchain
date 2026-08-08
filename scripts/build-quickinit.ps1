param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $BuildArgs
)

python "$PSScriptRoot\build-quickinit.py" @BuildArgs
exit $LASTEXITCODE
