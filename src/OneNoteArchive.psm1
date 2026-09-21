Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:GraphRoot = 'https://graph.microsoft.com/v1.0/me/onenote'
$script:MinimumRequestIntervalSeconds = 10.0
$script:LastRequestStartedAt = [DateTimeOffset]::MinValue

function Set-OneNoteRequestInterval {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [ValidateRange(0, 300)]
        [double] $Seconds
    )

    $script:MinimumRequestIntervalSeconds = $Seconds
    $script:LastRequestStartedAt = [DateTimeOffset]::MinValue
}

function Wait-OneNoteRequestSlot {
    [CmdletBinding()]
    param()

    if ($script:MinimumRequestIntervalSeconds -le 0) {
        $script:LastRequestStartedAt = [DateTimeOffset]::UtcNow
        return
    }

    $now = [DateTimeOffset]::UtcNow
    $elapsedSeconds = ($now - $script:LastRequestStartedAt).TotalSeconds
    $remainingSeconds = $script:MinimumRequestIntervalSeconds - $elapsedSeconds
    if ($remainingSeconds -gt 0) {
        $milliseconds = [int] [Math]::Ceiling($remainingSeconds * 1000)
        Start-Sleep -Milliseconds $milliseconds
    }
    $script:LastRequestStartedAt = [DateTimeOffset]::UtcNow
}

function ConvertTo-SafeName {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][AllowEmptyString()][string] $Name,
        [int] $MaximumLength = 100,
        [string] $Fallback = 'untitled'
    )

    $safe = $Name -replace '[\x00-\x1f<>:"/\\|?*]', '-'
    $safe = $safe -replace '\s+', ' '
    $safe = $safe.Trim().TrimEnd('.')
    if ([string]::IsNullOrWhiteSpace($safe)) {
        $safe = $Fallback
    }
    if ($safe.Length -gt $MaximumLength) {
        $safe = $safe.Substring(0, $MaximumLength).Trim().TrimEnd('.')
    }
    return $safe
}

function Get-StableId {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string] $Value,
        [ValidateRange(6, 64)][int] $Length = 10
    )

    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
    $hash = [System.Security.Cryptography.SHA256]::HashData($bytes)
    $hex = [Convert]::ToHexString($hash).ToLowerInvariant()
    return $hex.Substring(0, $Length)
}

function Write-Utf8NoBom {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string] $Path,
        [Parameter(Mandatory)][AllowEmptyString()][string] $Content
    )

    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))
}

function Write-JsonFile {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string] $Path,
        [Parameter(Mandatory)][AllowNull()][object] $Value,
        [int] $Depth = 50
    )

    $json = $Value | ConvertTo-Json -Depth $Depth
    Write-Utf8NoBom -Path $Path -Content ($json + [Environment]::NewLine)
}

function Get-FileIntegrity {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string] $Path)

    $item = Get-Item -LiteralPath $Path
    $hash = Get-FileHash -LiteralPath $Path -Algorithm SHA256
    return [ordered]@{
        size = $item.Length
        sha256 = $hash.Hash.ToLowerInvariant()
    }
}

function Connect-OneNoteGraph {
    [CmdletBinding()]
    param()

    if (-not (Get-Module -ListAvailable -Name Microsoft.Graph.Authentication)) {
        throw 'Microsoft.Graph.Authentication 모듈이 없습니다. 먼저 ./scripts/setup.fish를 실행하세요.'
    }

    Import-Module Microsoft.Graph.Authentication -ErrorAction Stop
    $context = Get-MgContext -ErrorAction SilentlyContinue
    if ($null -ne $context -and $context.Account -and @($context.Scopes) -contains 'Notes.Read') {
        Write-Host "저장된 Microsoft Graph 로그인 사용: $($context.Account)"
        return
    }

    Connect-MgGraph `
        -TenantId consumers `
        -Scopes 'Notes.Read' `
        -UseDeviceCode `
        -ContextScope CurrentUser `
        -NoWelcome
}

function Disconnect-OneNoteGraph {
    [CmdletBinding()]
    param()

    if (-not (Get-Module -ListAvailable -Name Microsoft.Graph.Authentication)) {
        return
    }
    Import-Module Microsoft.Graph.Authentication -ErrorAction Stop
    Disconnect-MgGraph -ErrorAction SilentlyContinue | Out-Null
    Write-Host '저장된 Microsoft Graph 로그인을 삭제했습니다.'
}

function Get-GraphStatusCode {
    [CmdletBinding()]
    param([Parameter(Mandatory)] $ErrorRecord)

    try {
        if ($null -ne $ErrorRecord.Exception.Response.StatusCode) {
            return [int] $ErrorRecord.Exception.Response.StatusCode
        }
    }
    catch {
        # Some Graph SDK exceptions don't expose Response after its internal retries.
    }

    $errorText = "$ErrorRecord`n$($ErrorRecord.Exception)"
    if ($errorText -match 'TooManyRequests|\b20166\b|status\s+code\s*:\s*429|\bHTTP\s+429\b') {
        return 429
    }
    return 0
}

function Invoke-OneNoteGraphRequest {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string] $Uri,
        [ValidateSet('GET')][string] $Method = 'GET',
        [string] $OutputFilePath,
        [ValidateRange(1, 10)][int] $MaximumAttempts = 6
    )

    $attempt = 0
    $throttleAttempt = 0
    while ($true) {
        Wait-OneNoteRequestSlot
        try {
            $previousProgressPreference = $ProgressPreference
            $ProgressPreference = 'SilentlyContinue'
            if ($OutputFilePath) {
                $parent = Split-Path -Parent $OutputFilePath
                New-Item -ItemType Directory -Path $parent -Force | Out-Null
                $temporaryPath = "$OutputFilePath.part"
                if (Test-Path -LiteralPath $temporaryPath) {
                    Remove-Item -LiteralPath $temporaryPath -Force
                }

                Invoke-MgGraphRequest `
                    -Method $Method `
                    -Uri $Uri `
                    -OutputFilePath $temporaryPath `
                    -ErrorAction Stop | Out-Null

                Move-Item -LiteralPath $temporaryPath -Destination $OutputFilePath -Force
                return
            }

            return Invoke-MgGraphRequest -Method $Method -Uri $Uri -ErrorAction Stop
        }
        catch {
            $statusCode = Get-GraphStatusCode -ErrorRecord $_
            if ($statusCode -eq 429) {
                $throttleAttempt++
                $exponent = [Math]::Min($throttleAttempt - 1, 4)
                $delaySeconds = [int] [Math]::Min(900, 60 * [Math]::Pow(2, $exponent))
                Write-Warning "OneNote API 사용량 제한(429/20166)입니다. $delaySeconds초 쉬고 같은 요청을 재시도합니다. 중단할 필요가 없습니다."
                Start-Sleep -Seconds $delaySeconds
                continue
            }

            $attempt++
            $retryable = $statusCode -eq 408 -or $statusCode -ge 500
            if (-not $retryable -or $attempt -ge $MaximumAttempts) {
                throw
            }

            $delaySeconds = [Math]::Min(60, [Math]::Pow(2, $attempt))
            Write-Warning "Graph 요청 실패(HTTP $statusCode). $delaySeconds초 후 재시도합니다. ($attempt/$MaximumAttempts)"
            Start-Sleep -Seconds $delaySeconds
        }
        finally {
            if ($null -ne $previousProgressPreference) {
                $ProgressPreference = $previousProgressPreference
            }
        }
    }
}

function Get-OneNoteGraphCollection {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string] $Uri)

    $items = [System.Collections.Generic.List[object]]::new()
    $nextUri = $Uri
    while ($nextUri) {
        $response = Invoke-OneNoteGraphRequest -Uri $nextUri
        if ($null -ne $response.value) {
            foreach ($item in @($response.value)) {
                $items.Add($item)
            }
        }

        $nextUri = $null
        if ($response -is [System.Collections.IDictionary] -and $response.Contains('@odata.nextLink')) {
            $nextUri = [string] $response['@odata.nextLink']
        }
        elseif ($null -ne $response.PSObject.Properties['@odata.nextLink']) {
            $nextUri = [string] $response.'@odata.nextLink'
        }
    }
    return $items.ToArray()
}

function Get-OneNoteNotebooks {
    [CmdletBinding()]
    param()

    $uri = "$script:GraphRoot/notebooks?`$top=100&`$select=id,displayName,createdDateTime,lastModifiedDateTime,isDefault,links"
    return @(Get-OneNoteGraphCollection -Uri $uri) | Sort-Object displayName
}

function ConvertFrom-NumberSelection {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string] $Selection,
        [Parameter(Mandatory)][ValidateRange(1, 100000)][int] $Maximum
    )

    $numbers = [System.Collections.Generic.HashSet[int]]::new()
    foreach ($partValue in ($Selection -split ',')) {
        $part = $partValue.Trim()
        if (-not $part) {
            continue
        }

        if ($part -match '^(\d+)-(\d+)$') {
            $start = [int] $Matches[1]
            $end = [int] $Matches[2]
            if ($start -gt $end) {
                throw "잘못된 범위입니다: $part"
            }
            foreach ($number in $start..$end) {
                if ($number -lt 1 -or $number -gt $Maximum) {
                    throw "선택 번호가 범위를 벗어났습니다: $number"
                }
                [void] $numbers.Add($number)
            }
            continue
        }

        if ($part -notmatch '^\d+$') {
            throw "선택 형식을 이해할 수 없습니다: $part"
        }
        $number = [int] $part
        if ($number -lt 1 -or $number -gt $Maximum) {
            throw "선택 번호가 범위를 벗어났습니다: $number"
        }
        [void] $numbers.Add($number)
    }

    if ($numbers.Count -eq 0) {
        throw '노트북을 하나 이상 선택해야 합니다.'
    }
    return @($numbers | Sort-Object)
}

function Get-SectionGroupSections {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] $Group,
        [Parameter(Mandatory)][AllowEmptyCollection()][string[]] $ParentPath
    )

    $result = [System.Collections.Generic.List[object]]::new()
    $groupId = [uri]::EscapeDataString([string] $Group.id)
    $groupSegment = "$(ConvertTo-SafeName -Name ([string] $Group.displayName))--$(Get-StableId -Value ([string] $Group.id) -Length 8)"
    $groupPath = @($ParentPath) + @($groupSegment)

    $sectionsUri = "$script:GraphRoot/sectionGroups/$groupId/sections?`$top=100&`$select=id,displayName,createdDateTime,lastModifiedDateTime,isDefault,links"
    foreach ($section in @(Get-OneNoteGraphCollection -Uri $sectionsUri)) {
        $result.Add([pscustomobject]@{ Section = $section; Path = $groupPath })
    }

    $groupsUri = "$script:GraphRoot/sectionGroups/$groupId/sectionGroups?`$top=100&`$select=id,displayName,createdDateTime,lastModifiedDateTime"
    foreach ($childGroup in @(Get-OneNoteGraphCollection -Uri $groupsUri)) {
        foreach ($entry in @(Get-SectionGroupSections -Group $childGroup -ParentPath $groupPath)) {
            $result.Add($entry)
        }
    }
    return $result.ToArray()
}

function Get-OneNoteNotebookSections {
    [CmdletBinding()]
    param([Parameter(Mandatory)] $Notebook)

    $result = [System.Collections.Generic.List[object]]::new()
    $notebookId = [uri]::EscapeDataString([string] $Notebook.id)
    $sectionsUri = "$script:GraphRoot/notebooks/$notebookId/sections?`$top=100&`$select=id,displayName,createdDateTime,lastModifiedDateTime,isDefault,links"
    foreach ($section in @(Get-OneNoteGraphCollection -Uri $sectionsUri)) {
        $result.Add([pscustomobject]@{ Section = $section; Path = @() })
    }

    $groupsUri = "$script:GraphRoot/notebooks/$notebookId/sectionGroups?`$top=100&`$select=id,displayName,createdDateTime,lastModifiedDateTime"
    foreach ($group in @(Get-OneNoteGraphCollection -Uri $groupsUri)) {
        foreach ($entry in @(Get-SectionGroupSections -Group $group -ParentPath @())) {
            $result.Add($entry)
        }
    }
    return $result.ToArray()
}

function Get-OneNoteSectionPages {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string] $SectionId)

    $encodedId = [uri]::EscapeDataString($SectionId)
    $uri = "$script:GraphRoot/sections/$encodedId/pages?pagelevel=true&`$top=100&`$select=id,title,createdDateTime,lastModifiedDateTime,level,order,links,contentUrl"
    return @(Get-OneNoteGraphCollection -Uri $uri) | Sort-Object order
}

function Get-HtmlAttribute {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string] $Tag,
        [Parameter(Mandatory)][string] $Name
    )

    $pattern = '\b' + [regex]::Escape($Name) + '\s*=\s*(?:"(?<double>[^"]*)"|''(?<single>[^'']*)'')'
    $match = [regex]::Match($Tag, $pattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
    if (-not $match.Success) {
        return $null
    }
    if ($match.Groups['double'].Success) {
        return [System.Net.WebUtility]::HtmlDecode($match.Groups['double'].Value)
    }
    return [System.Net.WebUtility]::HtmlDecode($match.Groups['single'].Value)
}

function Get-CssPixelValue {
    [CmdletBinding()]
    param(
        [AllowNull()][string] $Style,
        [Parameter(Mandatory)][string] $Property
    )

    if (-not $Style) {
        return $null
    }
    $pattern = '(?:^|;)\s*' + [regex]::Escape($Property) + '\s*:\s*(?<value>-?\d+(?:\.\d+)?)px'
    $match = [regex]::Match($Style, $pattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
    if (-not $match.Success) {
        return $null
    }
    return [double]::Parse($match.Groups['value'].Value, [System.Globalization.CultureInfo]::InvariantCulture)
}

function Get-OneNoteLayout {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string] $Html)

    $blocks = [System.Collections.Generic.List[object]]::new()
    $options = [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
    foreach ($match in [regex]::Matches($Html, '<(?<tag>div|img|object)\b[^>]*>', $options)) {
        $tagHtml = $match.Value
        $style = Get-HtmlAttribute -Tag $tagHtml -Name 'style'
        if (-not $style -or $style -notmatch 'position\s*:\s*absolute') {
            continue
        }
        $blocks.Add([ordered]@{
            tag = $match.Groups['tag'].Value.ToLowerInvariant()
            id = Get-HtmlAttribute -Tag $tagHtml -Name 'id'
            dataId = Get-HtmlAttribute -Tag $tagHtml -Name 'data-id'
            top = Get-CssPixelValue -Style $style -Property 'top'
            left = Get-CssPixelValue -Style $style -Property 'left'
            width = Get-CssPixelValue -Style $style -Property 'width'
            height = Get-CssPixelValue -Style $style -Property 'height'
            style = $style
            htmlOffset = $match.Index
        })
    }

    $inkMarkerCount = [regex]::Matches(
        $Html,
        'inkml|data-render-src|application/ink',
        [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
    ).Count

    return [ordered]@{
        absoluteBlockCount = $blocks.Count
        inkMarkerCount = $inkMarkerCount
        needsVisualReview = $blocks.Count -ge 2 -or $inkMarkerCount -gt 0
        blocks = $blocks.ToArray()
    }
}

function Get-ResourceIdFromUrl {
    [CmdletBinding()]
    param([AllowNull()][string] $Url)

    if (-not $Url) {
        return $null
    }
    $match = [regex]::Match($Url, '/resources/(?<id>[^/?#]+)/\$value', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
    if (-not $match.Success) {
        return $null
    }
    return [uri]::UnescapeDataString($match.Groups['id'].Value)
}

function Get-ExtensionForMimeType {
    [CmdletBinding()]
    param([AllowNull()][string] $MimeType)

    $normalized = if ($MimeType) { ($MimeType -split ';')[0].Trim().ToLowerInvariant() } else { '' }
    $extensions = @{
        'image/png' = '.png'; 'image/jpeg' = '.jpg'; 'image/gif' = '.gif'
        'image/webp' = '.webp'; 'image/svg+xml' = '.svg'; 'image/tiff' = '.tiff'
        'application/pdf' = '.pdf'; 'application/zip' = '.zip'; 'text/plain' = '.txt'
    }
    if ($extensions.ContainsKey($normalized)) {
        return $extensions[$normalized]
    }
    return '.bin'
}

function Get-OneNoteHtmlResources {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string] $Html)

    $resources = [System.Collections.Generic.List[object]]::new()
    $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    $imageNumber = 0
    $options = [System.Text.RegularExpressions.RegexOptions]::IgnoreCase

    foreach ($match in [regex]::Matches($Html, '<img\b[^>]*>', $options)) {
        $tag = $match.Value
        $fullUrl = Get-HtmlAttribute -Tag $tag -Name 'data-fullres-src'
        $displayUrl = Get-HtmlAttribute -Tag $tag -Name 'src'
        $preferredUrl = if ($fullUrl) { $fullUrl } else { $displayUrl }
        $resourceId = Get-ResourceIdFromUrl -Url $preferredUrl
        if (-not $resourceId -or -not $seen.Add($resourceId)) {
            continue
        }

        $imageNumber++
        $mime = Get-HtmlAttribute -Tag $tag -Name 'data-fullres-src-type'
        if (-not $mime) {
            $mime = Get-HtmlAttribute -Tag $tag -Name 'data-src-type'
        }
        $resources.Add([pscustomobject]@{
            ResourceId = $resourceId
            Kind = 'image'
            FileName = ('image-{0:d3}{1}' -f $imageNumber, (Get-ExtensionForMimeType -MimeType $mime))
            MimeType = $mime
            SourceUrls = @($fullUrl, $displayUrl) | Where-Object { $_ }
        })
    }

    foreach ($match in [regex]::Matches($Html, '<object\b[^>]*>', $options)) {
        $tag = $match.Value
        $url = Get-HtmlAttribute -Tag $tag -Name 'data'
        $resourceId = Get-ResourceIdFromUrl -Url $url
        if (-not $resourceId -or -not $seen.Add($resourceId)) {
            continue
        }

        $mime = Get-HtmlAttribute -Tag $tag -Name 'type'
        $attachmentName = Get-HtmlAttribute -Tag $tag -Name 'data-attachment'
        if (-not $attachmentName) {
            $extension = Get-ExtensionForMimeType -MimeType $mime
            $attachmentName = "attachment-$(Get-StableId -Value $resourceId -Length 8)$extension"
        }
        $resources.Add([pscustomobject]@{
            ResourceId = $resourceId
            Kind = 'attachment'
            FileName = ConvertTo-SafeName -Name $attachmentName -MaximumLength 120 -Fallback 'attachment.bin'
            MimeType = $mime
            SourceUrls = @($url)
        })
    }
    return $resources.ToArray()
}

function Get-ExternalMediaReferences {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string] $Html)

    $references = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    $options = [System.Text.RegularExpressions.RegexOptions]::IgnoreCase

    foreach ($match in [regex]::Matches($Html, '<img\b[^>]*>', $options)) {
        $tag = $match.Value
        $url = Get-HtmlAttribute -Tag $tag -Name 'data-fullres-src'
        if (-not $url) {
            $url = Get-HtmlAttribute -Tag $tag -Name 'src'
        }
        if ($url -match '^https?://' -and -not (Get-ResourceIdFromUrl -Url $url)) {
            [void] $references.Add($url)
        }
    }

    foreach ($match in [regex]::Matches($Html, '<iframe\b[^>]*>', $options)) {
        $url = Get-HtmlAttribute -Tag $match.Value -Name 'src'
        if ($url -match '^https?://') {
            [void] $references.Add($url)
        }
    }

    foreach ($match in [regex]::Matches($Html, '<object\b[^>]*>', $options)) {
        $url = Get-HtmlAttribute -Tag $match.Value -Name 'data'
        if ($url -match '^https?://' -and -not (Get-ResourceIdFromUrl -Url $url)) {
            [void] $references.Add($url)
        }
    }

    return @($references | Sort-Object)
}

function Convert-HtmlResourceUrls {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string] $Html,
        [Parameter(Mandatory)][AllowEmptyCollection()][object[]] $Resources
    )

    $localized = $Html
    foreach ($resource in $Resources) {
        $relativePath = "assets/$($resource.FileName)"
        foreach ($sourceUrl in @($resource.SourceUrls)) {
            if ($sourceUrl) {
                $localized = $localized.Replace($sourceUrl, $relativePath)
                $localized = $localized.Replace([System.Net.WebUtility]::HtmlEncode($sourceUrl), $relativePath)
            }
        }
    }
    return $localized
}

function Export-OneNotePage {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] $Page,
        [Parameter(Mandatory)][string] $ArchiveSectionPath,
        [switch] $Force
    )

    $pageStableId = Get-StableId -Value ([string] $Page.id)
    $archivePagePath = Join-Path $ArchiveSectionPath $pageStableId
    $metadataPath = Join-Path $archivePagePath 'page.json'
    $layoutPath = Join-Path $archivePagePath 'layout.json'
    $rawHtmlPath = Join-Path $archivePagePath 'page.raw.html'
    $localHtmlPath = Join-Path $archivePagePath 'page.local.html'
    $assetsPath = Join-Path $archivePagePath 'assets'

    if (-not $Force -and (Test-Path -LiteralPath $metadataPath) -and (Test-Path -LiteralPath $rawHtmlPath) -and (Test-Path -LiteralPath $localHtmlPath)) {
        try {
            $existing = Get-Content -LiteralPath $metadataPath -Raw -Encoding utf8 | ConvertFrom-Json
            if ($existing.lastModifiedDateTime -eq $Page.lastModifiedDateTime) {
                $existingNeedsReview = if ($null -ne $existing.PSObject.Properties['needsVisualReview']) {
                    [bool] $existing.needsVisualReview
                }
                else {
                    [bool] $existing.layout.needsVisualReview
                }
                $existingExternalCount = if ($null -ne $existing.PSObject.Properties['externalMediaReferences']) {
                    @($existing.externalMediaReferences).Count
                }
                else {
                    0
                }
                return [pscustomobject]@{
                    Status = 'skipped'
                    ResourceCount = @($existing.resources).Count
                    AttachmentCount = @($existing.resources | Where-Object kind -eq 'attachment').Count
                    ExternalMediaReferenceCount = $existingExternalCount
                    NeedsVisualReview = $existingNeedsReview
                }
            }
        }
        catch {
            Write-Warning "기존 메타데이터를 읽지 못해 다시 받습니다: $metadataPath"
        }
    }

    New-Item -ItemType Directory -Path $archivePagePath, $assetsPath -Force | Out-Null
    $encodedPageId = [uri]::EscapeDataString([string] $Page.id)
    $contentUri = "$script:GraphRoot/pages/$encodedPageId/content?includeIDs=true"
    Invoke-OneNoteGraphRequest -Uri $contentUri -OutputFilePath $rawHtmlPath

    $html = Get-Content -LiteralPath $rawHtmlPath -Raw -Encoding utf8
    $layout = Get-OneNoteLayout -Html $html
    $resources = @(Get-OneNoteHtmlResources -Html $html)
    $externalMediaReferences = @(Get-ExternalMediaReferences -Html $html)
    $needsVisualReview = [bool] $layout.needsVisualReview -or $externalMediaReferences.Count -gt 0
    $resourceMetadata = [System.Collections.Generic.List[object]]::new()
    $usedNames = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

    foreach ($resource in $resources) {
        $fileName = [string] $resource.FileName
        if (-not $usedNames.Add($fileName)) {
            $baseName = [System.IO.Path]::GetFileNameWithoutExtension($fileName)
            $extension = [System.IO.Path]::GetExtension($fileName)
            $fileName = "$baseName-$(Get-StableId -Value $resource.ResourceId -Length 8)$extension"
            [void] $usedNames.Add($fileName)
        }
        $resource.FileName = $fileName

        $encodedResourceId = [uri]::EscapeDataString([string] $resource.ResourceId)
        $resourceUri = "$script:GraphRoot/resources/$encodedResourceId/`$value"
        $resourcePath = Join-Path $assetsPath $fileName
        Invoke-OneNoteGraphRequest -Uri $resourceUri -OutputFilePath $resourcePath
        $integrity = Get-FileIntegrity -Path $resourcePath
        $resourceMetadata.Add([ordered]@{
            id = $resource.ResourceId
            kind = $resource.Kind
            fileName = $fileName
            mimeType = $resource.MimeType
            size = $integrity.size
            sha256 = $integrity.sha256
        })
    }

    $localHtml = Convert-HtmlResourceUrls -Html $html -Resources $resources
    Write-Utf8NoBom -Path $localHtmlPath -Content $localHtml
    Write-JsonFile -Path $layoutPath -Value $layout
    $rawHtmlIntegrity = Get-FileIntegrity -Path $rawHtmlPath
    $localHtmlIntegrity = Get-FileIntegrity -Path $localHtmlPath

    $metadata = [ordered]@{
        id = $Page.id
        stableId = $pageStableId
        title = $Page.title
        createdDateTime = $Page.createdDateTime
        lastModifiedDateTime = $Page.lastModifiedDateTime
        level = $Page.level
        order = $Page.order
        links = $Page.links
        needsVisualReview = $needsVisualReview
        layout = $layout
        externalMediaReferences = $externalMediaReferences
        resources = $resourceMetadata.ToArray()
        files = [ordered]@{
            rawHtml = $rawHtmlIntegrity
            localHtml = $localHtmlIntegrity
        }
        exportedAt = [DateTimeOffset]::UtcNow.ToString('o')
    }
    Write-JsonFile -Path $metadataPath -Value $metadata

    return [pscustomobject]@{
        Status = 'exported'
        ResourceCount = $resourceMetadata.Count
        AttachmentCount = @($resourceMetadata | Where-Object kind -eq 'attachment').Count
        ExternalMediaReferenceCount = $externalMediaReferences.Count
        NeedsVisualReview = $needsVisualReview
    }
}

Export-ModuleMember -Function @(
    'Connect-OneNoteGraph',
    'ConvertFrom-NumberSelection',
    'ConvertTo-SafeName',
    'Disconnect-OneNoteGraph',
    'Export-OneNotePage',
    'Get-OneNoteNotebookSections',
    'Get-OneNoteNotebooks',
    'Get-OneNoteSectionPages',
    'Get-StableId',
    'Set-OneNoteRequestInterval',
    'Write-JsonFile'
)
