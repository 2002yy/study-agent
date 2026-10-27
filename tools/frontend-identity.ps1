# Frontend identity probe.
#
# The launcher must refuse to adopt whatever else happens to hold port 5173, so
# this cannot degrade to "HTTP 200 means it is us". It also must not key on
# user-facing copy: the previous check matched a hardcoded English <title> that
# went stale when the real title became Chinese, and a healthy dev server was
# reported as "not the Study Agent frontend".
#
# The identity is therefore an explicit marker declared by the app's own entry
# HTML (frontend/index.html) and read here. Both the launcher and the tests use
# this function, so the marker cannot drift away from its check silently.

$MarkerName = "study-agent-app"
$MarkerValue = "study-agent"

function Test-StudyAgentFrontendContent {
    param([string]$Content)

    if ([string]::IsNullOrWhiteSpace($Content)) { return $false }

    # Accept the marker regardless of attribute order, spacing or quote style,
    # but require name and content on the same <meta> tag.
    foreach ($tag in [regex]::Matches($Content, '(?is)<meta\b[^>]*>')) {
        $attributes = $tag.Value
        $namePattern = '(?i)\bname\s*=\s*["'']' + [regex]::Escape($MarkerName) + '["'']'
        $valuePattern = '(?i)\bcontent\s*=\s*["'']' + [regex]::Escape($MarkerValue) + '["'']'
        if ($attributes -match $namePattern -and $attributes -match $valuePattern) {
            return $true
        }
    }
    return $false
}
