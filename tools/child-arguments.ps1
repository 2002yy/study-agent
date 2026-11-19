# Child-process argument quoting.
#
# Start-Process -ArgumentList joins an array with single spaces and never adds
# quotes. A path such as `C:\Users\Zhang\Desktop\study agent\frontend\...`
# therefore reached Node as two arguments and the dev server failed with
# `Cannot find module 'C:\Users\Zhang\Desktop\study'`.
#
# This helper applies the quoting rules the Windows C runtime uses to split a
# command line: wrap the argument in double quotes and double the backslashes
# that sit immediately before a quote or the closing quote. Arguments without
# whitespace or quotes stay untouched.

function ConvertTo-ChildArgumentLine {
    param([string[]]$Arguments)

    $parts = foreach ($argument in $Arguments) {
        if ([string]::IsNullOrEmpty($argument)) {
            '""'
            continue
        }
        if ($argument -notmatch '[\s"]') {
            $argument
            continue
        }

        $builder = [System.Text.StringBuilder]::new()
        [void]$builder.Append('"')
        $backslashes = 0
        foreach ($character in $argument.ToCharArray()) {
            if ($character -eq '\') {
                $backslashes++
                continue
            }
            if ($character -eq '"') {
                [void]$builder.Append('\' * ($backslashes * 2 + 1))
                [void]$builder.Append('"')
                $backslashes = 0
                continue
            }
            if ($backslashes -gt 0) {
                [void]$builder.Append('\' * $backslashes)
                $backslashes = 0
            }
            [void]$builder.Append($character)
        }
        # Backslashes before the closing quote must be doubled as well.
        if ($backslashes -gt 0) {
            [void]$builder.Append('\' * ($backslashes * 2))
        }
        [void]$builder.Append('"')
        $builder.ToString()
    }

    return ($parts -join ' ')
}
