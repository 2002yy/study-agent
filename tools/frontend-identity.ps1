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
#
# What counts as a declaration is deliberately narrow:
#   - the marker must be a real <meta> element, not a comment and not a tag
#     whose name merely starts with "meta" (metadata, meta-data);
#   - the attributes must be attributes, not attribute values or hyphenated
#     look-alikes: `data-name="study-agent-app"` declares nothing.

$MarkerName = "study-agent-app"
$MarkerValue = "study-agent"

function Test-StudyAgentFrontendContent {
    param([string]$Content)

    if ([string]::IsNullOrWhiteSpace($Content)) { return $false }

    # A page that merely documents the marker in a comment does not identify
    # itself as the app.
    $markup = [regex]::Replace($Content, '(?s)<!--.*?-->', '')

    # `\s` before the attribute name is what rejects `data-name` / `data-content`:
    # a hyphen is not whitespace, so the name never matches inside a compound
    # attribute. Quoting is required, as the entry page declares it.
    $namePattern = '(?i)(?:^|\s)name\s*=\s*["'']' + [regex]::Escape($MarkerName) + '["'']'
    $valuePattern = '(?i)(?:^|\s)content\s*=\s*["'']' + [regex]::Escape($MarkerValue) + '["'']'

    # `(?=[\s/>])` keeps <metadata> and <meta-data> from being treated as <meta>.
    foreach ($tag in [regex]::Matches($markup, '(?is)<meta(?=[\s/>])[^>]*>')) {
        $attributes = $tag.Value
        if ($attributes -match $namePattern -and $attributes -match $valuePattern) {
            return $true
        }
    }
    return $false
}
