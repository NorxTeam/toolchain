param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $BuildArgs
)

python "$PSScriptRoot\build-rust-userspace.py" @BuildArgs
exit $LASTEXITCODE
