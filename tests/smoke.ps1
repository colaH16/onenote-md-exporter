#!/usr/bin/env pwsh

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$modulePath = Join-Path $PSScriptRoot '../src/OneNoteArchive.psm1'
Import-Module $modulePath -Force
Set-OneNoteRequestInterval -Seconds 0

function Assert-Equal {
    param($Expected, $Actual, [string] $Message)
    if ($Expected -ne $Actual) {
        throw "$Message`nExpected: $Expected`nActual:   $Actual"
    }
}

$ambiguousInterpolationPattern = '\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7F]'
$ambiguousInterpolations = @(
    foreach ($sourceFile in @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot '..') -Recurse -File -Include '*.ps1', '*.psm1')) {
        $lineNumber = 0
        foreach ($line in [System.IO.File]::ReadLines($sourceFile.FullName)) {
            $lineNumber++
            if ($line -match $ambiguousInterpolationPattern) {
                "{0}:{1}: {2}" -f $sourceFile.FullName, $lineNumber, $line.Trim()
            }
        }
    }
)
Assert-Equal 0 $ambiguousInterpolations.Count ("한글과 붙은 모호한 변수 보간이 있습니다:`n" + ($ambiguousInterpolations -join "`n"))

Assert-Equal 'a-b-c' (ConvertTo-SafeName -Name 'a/b:c') '파일명 금지 문자를 치환해야 합니다.'
Assert-Equal 'untitled' (ConvertTo-SafeName -Name '   ') '빈 제목은 fallback을 사용해야 합니다.'
Assert-Equal 10 ((Get-StableId -Value 'same input').Length) '안정 ID 길이가 잘못됐습니다.'
Assert-Equal (Get-StableId -Value 'same input') (Get-StableId -Value 'same input') '안정 ID가 결정적이지 않습니다.'

$selection = @(ConvertFrom-NumberSelection -Selection '1,3,5-7,6' -Maximum 10)
Assert-Equal '1,3,5,6,7' ($selection -join ',') '번호 선택 파싱이 잘못됐습니다.'

$sampleHtml = @'
<html><body data-absolute-enabled="true">
  <div id="main" data-id="main" style="position:absolute;top:120px;left:48px;width:500px">term</div>
  <div id="note" data-id="note" style="position:absolute;top:120px;left:600px;width:200px">annotation</div>
  <img src="https://graph.microsoft.com/v1.0/me/onenote/resources/web/$value"
       data-fullres-src="https://graph.microsoft.com/v1.0/me/onenote/resources/full/$value"
       data-fullres-src-type="image/png" />
  <object data="https://graph.microsoft.com/v1.0/me/onenote/resources/file/$value"
          data-attachment="example.pdf" type="application/pdf" />
  <iframe src="https://www.youtube.com/embed/example"></iframe>
</body></html>
'@

$archiveModule = Get-Module OneNoteArchive
$layout = & $archiveModule { param($Html) Get-OneNoteLayout -Html $Html } $sampleHtml
Assert-Equal 2 $layout.absoluteBlockCount '절대 위치 블록을 모두 찾아야 합니다.'
Assert-Equal $true $layout.needsVisualReview '여러 자유 배치 블록은 시각 검토 대상으로 표시해야 합니다.'

$resources = @(& $archiveModule { param($Html) Get-OneNoteHtmlResources -Html $Html } $sampleHtml)
Assert-Equal 2 $resources.Count '이미지와 첨부 리소스를 찾아야 합니다.'
Assert-Equal 'image' $resources[0].Kind '첫 리소스는 이미지여야 합니다.'
Assert-Equal 'attachment' $resources[1].Kind '두 번째 리소스는 첨부파일이어야 합니다.'

$localized = & $archiveModule {
    param($Html, $Resources)
    Convert-HtmlResourceUrls -Html $Html -Resources $Resources
} $sampleHtml $resources
Assert-Equal $true ($localized.Contains('assets/image-001.png')) '이미지 URL을 로컬 경로로 변경해야 합니다.'
Assert-Equal $true ($localized.Contains('assets/example.pdf')) '첨부 URL을 로컬 경로로 변경해야 합니다.'

$externalReferences = @(& $archiveModule {
    param($Html)
    Get-ExternalMediaReferences -Html $Html
} $sampleHtml)
Assert-Equal 1 $externalReferences.Count '외부 iframe 참조를 기록해야 합니다.'

$throttleStatus = 0
try {
    throw [System.Exception]::new('HTTP request failed: TooManyRequests, OneNote error 20166')
}
catch {
    $throttleStatus = & $archiveModule {
        param($ErrorRecord)
        Get-GraphStatusCode -ErrorRecord $ErrorRecord
    } $_
}
Assert-Equal 429 $throttleStatus 'SDK가 감싼 OneNote 20166 오류를 429로 감지해야 합니다.'

$gatewayTimeoutStatus = 0
try {
    throw [System.Exception]::new('HTTP request failed with status code: GatewayTimeout.')
}
catch {
    $gatewayTimeoutStatus = & $archiveModule {
        param($ErrorRecord)
        Get-GraphStatusCode -ErrorRecord $ErrorRecord
    } $_
}
Assert-Equal 504 $gatewayTimeoutStatus 'SDK가 이름으로만 남긴 GatewayTimeout을 504로 감지해야 합니다.'

$throttleRetryCalls = & $archiveModule {
    $script:ThrottleRetryCalls = 0
    function Invoke-MgGraphRequest {
        param([string] $Method, [string] $Uri)

        $script:ThrottleRetryCalls++
        if ($script:ThrottleRetryCalls -eq 1) {
            throw [System.Exception]::new('HTTP request failed: TooManyRequests, OneNote error 20166')
        }
        return [pscustomobject]@{ value = @() }
    }
    function Start-Sleep {
        param([int] $Seconds)
    }

    [void] (Invoke-OneNoteGraphRequest -Uri 'https://graph.microsoft.com/v1.0/me/onenote/notebooks')
    return $script:ThrottleRetryCalls
}
Assert-Equal 2 $throttleRetryCalls '429 경고를 출력한 뒤 같은 요청을 재시도해야 합니다.'

$temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) "onenote-md-exporter-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $temporaryRoot -Force | Out-Null
try {
    $exportResult = & $archiveModule {
        param($ArchivePath, $Html)

        $script:FakePageHtml = $Html
        function Invoke-MgGraphRequest {
            [CmdletBinding()]
            param(
                [string] $Method,
                [string] $Uri,
                [string] $OutputFilePath
            )

            if ($Uri -match '/pages/.+/content') {
                [System.IO.File]::WriteAllText($OutputFilePath, $script:FakePageHtml, [System.Text.UTF8Encoding]::new($false))
            }
            else {
                [System.IO.File]::WriteAllBytes($OutputFilePath, [byte[]](1, 2, 3, 4))
            }
        }

        $page = [pscustomobject]@{
            id = 'page-id'
            title = 'Sample page'
            createdDateTime = '2026-01-01T00:00:00Z'
            lastModifiedDateTime = '2026-01-02T00:00:00Z'
            level = 0
            order = 0
            links = [pscustomobject]@{}
        }
        Export-OneNotePage -Page $page -ArchiveSectionPath $ArchivePath
    } $temporaryRoot $sampleHtml

    Assert-Equal 'exported' $exportResult.Status '페이지 전체 보존 흐름이 완료되어야 합니다.'
    Assert-Equal 2 $exportResult.ResourceCount '두 리소스가 저장되어야 합니다.'
    Assert-Equal 1 $exportResult.ExternalMediaReferenceCount '외부 iframe을 결과에 기록해야 합니다.'

    $pageDirectory = Get-ChildItem -LiteralPath $temporaryRoot -Directory | Select-Object -First 1
    Assert-Equal $true (Test-Path -LiteralPath (Join-Path $pageDirectory.FullName 'page.raw.html')) '원본 HTML이 없습니다.'
    Assert-Equal $true (Test-Path -LiteralPath (Join-Path $pageDirectory.FullName 'page.local.html')) '로컬 HTML이 없습니다.'
    Assert-Equal $true (Test-Path -LiteralPath (Join-Path $pageDirectory.FullName 'layout.json')) '배치 메타데이터가 없습니다.'

    $pageMetadata = Get-Content -LiteralPath (Join-Path $pageDirectory.FullName 'page.json') -Raw | ConvertFrom-Json
    Assert-Equal 64 $pageMetadata.files.rawHtml.sha256.Length '원본 HTML SHA-256이 기록되어야 합니다.'
    Assert-Equal 2 @($pageMetadata.resources).Count '리소스 메타데이터 수가 잘못됐습니다.'
    Assert-Equal 64 $pageMetadata.resources[0].sha256.Length '리소스 SHA-256이 기록되어야 합니다.'

    $verifyOutput = Join-Path $temporaryRoot 'verify-output'
    $verifySection = Join-Path $verifyOutput 'archive/notebook/section'
    New-Item -ItemType Directory -Path $verifySection -Force | Out-Null
    Write-JsonFile -Path (Join-Path $verifySection 'section.json') -Value ([ordered]@{ id = 'section-id' })

    $completePage = Join-Path $verifySection (Get-StableId -Value 'complete-page-id')
    $completeAssets = Join-Path $completePage 'assets'
    New-Item -ItemType Directory -Path $completeAssets -Force | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $completePage 'page.raw.html'), '<html>raw</html>')
    [System.IO.File]::WriteAllText((Join-Path $completePage 'page.local.html'), '<html>local</html>')
    Write-JsonFile -Path (Join-Path $completePage 'layout.json') -Value ([ordered]@{ absoluteBlockCount = 0 })
    Write-JsonFile -Path (Join-Path $completePage 'page.json') -Value ([ordered]@{
        title = 'Complete page'
        resources = @([ordered]@{ fileName = 'image.bin' })
    })
    [System.IO.File]::WriteAllBytes((Join-Path $completeAssets 'image.bin'), [byte[]](1, 2, 3))

    $incompletePageId = 'incomplete-page-id'
    $incompletePage = Join-Path $verifySection (Get-StableId -Value $incompletePageId)
    $incompleteAssets = Join-Path $incompletePage 'assets'
    New-Item -ItemType Directory -Path $incompleteAssets -Force | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $incompletePage 'page.raw.html'), '<html>partial</html>')
    [System.IO.File]::WriteAllText((Join-Path $incompleteAssets 'image.bin.part'), 'partial')

    $emptyPage = Join-Path $verifySection (Get-StableId -Value 'empty-page-id')
    New-Item -ItemType Directory -Path $emptyPage -Force | Out-Null
    Write-JsonFile -Path (Join-Path $verifyOutput 'manifest.json') -Value ([ordered]@{
        failures = @([ordered]@{
            pageId = $incompletePageId
            pageTitle = 'Incomplete page'
        })
    })

    $verification = Test-OneNoteArchive -OutputRoot $verifyOutput
    Assert-Equal 0 $verification.apiRequests '로컬 검증은 API를 호출하지 않아야 합니다.'
    Assert-Equal 3 $verification.pagesChecked '모든 페이지 디렉터리를 검사해야 합니다.'
    Assert-Equal 1 $verification.completePages '완전한 페이지 수가 잘못됐습니다.'
    Assert-Equal 2 $verification.incompletePages '불완전한 페이지 수가 잘못됐습니다.'
    $knownIncomplete = @($verification.issues | Where-Object title -eq 'Incomplete page')
    Assert-Equal 1 $knownIncomplete.Count 'manifest에서 실패한 페이지 제목을 찾아야 합니다.'
    Assert-Equal $incompletePageId $knownIncomplete[0].pageId 'manifest에서 복구할 페이지 ID를 찾아야 합니다.'
    Assert-Equal $true (@($knownIncomplete[0].missingFiles) -contains 'layout.json') '누락된 layout.json을 찾아야 합니다.'
    Assert-Equal 1 @($knownIncomplete[0].partFiles).Count '남은 .part 파일을 찾아야 합니다.'

    $repairResult = & $archiveModule {
        param($OutputRoot, $Html)

        $script:FakeRepairHtml = $Html
        function Invoke-MgGraphRequest {
            [CmdletBinding()]
            param(
                [string] $Method,
                [string] $Uri,
                [string] $OutputFilePath
            )

            if ($Uri -match '/pages/.+/content') {
                [System.IO.File]::WriteAllText($OutputFilePath, $script:FakeRepairHtml, [System.Text.UTF8Encoding]::new($false))
            }
            else {
                [System.IO.File]::WriteAllBytes($OutputFilePath, [byte[]](1, 2, 3, 4))
            }
        }

        function Get-OneNotePage {
            param([string] $PageId)
            return [pscustomobject]@{
                id = $PageId
                title = 'Incomplete page'
                createdDateTime = '2026-01-01T00:00:00Z'
                lastModifiedDateTime = '2026-01-02T00:00:00Z'
                level = 0
                order = 1
                links = [pscustomobject]@{}
            }
        }

        Repair-OneNoteArchive -OutputRoot $OutputRoot
    } $verifyOutput $sampleHtml
    Assert-Equal 1 $repairResult.repairedPages '복구 가능한 페이지만 다시 받아야 합니다.'
    Assert-Equal 0 $repairResult.failedPages '대상 페이지 복구가 실패했습니다.'
    Assert-Equal 1 $repairResult.unrepairablePages 'ID가 없는 빈 디렉터리는 자동 복구 불가로 남겨야 합니다.'
    Assert-Equal 1 $repairResult.remainingIncompletePages '복구 후 남은 불완전 페이지 수가 잘못됐습니다.'
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        [System.IO.Directory]::Delete($temporaryRoot, $true)
    }
}

$failedAsExpected = $false
try {
    [void] (ConvertFrom-NumberSelection -Selection '0,2' -Maximum 10)
}
catch {
    $failedAsExpected = $true
}
Assert-Equal $true $failedAsExpected '범위를 벗어난 선택을 거부해야 합니다.'

Write-Host 'Smoke tests passed.'
