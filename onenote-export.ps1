#!/usr/bin/env pwsh

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('help', 'login', 'list', 'init', 'init-conversion', 'export', 'verify', 'repair', 'logout')]
    [string] $Command = 'help',

    [string] $Config = './.local-config/export.json',
    [string] $ConversionConfig = './.local-config/markdown.json',
    [string] $Output,
    [switch] $Force,

    [ValidateRange(0, 300)]
    [double] $RequestIntervalSeconds = 10
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$modulePath = Join-Path $PSScriptRoot 'src/OneNoteArchive.psm1'
Import-Module $modulePath -Force

function Resolve-ProjectPath {
    param([Parameter(Mandatory)][string] $Path)

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot $Path))
}

function Show-Help {
    @'
OneNote Archive Exporter

사용법:
  pwsh ./onenote-export.ps1 login
  pwsh ./onenote-export.ps1 list
  pwsh ./onenote-export.ps1 init
  pwsh ./onenote-export.ps1 init-conversion
  pwsh ./onenote-export.ps1 export [-Force]
  pwsh ./onenote-export.ps1 verify
  pwsh ./onenote-export.ps1 repair
  pwsh ./onenote-export.ps1 logout

옵션:
  -Config <path>   백업 설정 파일. 기본값: ./.local-config/export.json
  -ConversionConfig <path>
                   Markdown 변환 설정. 기본값: ./.local-config/markdown.json
  -Output <path>   출력 디렉터리. 설정의 outputRoot보다 우선합니다.
  -Force           변경 여부와 관계없이 모든 페이지를 다시 받습니다.
  -RequestIntervalSeconds <seconds>
                   Graph 요청 사이의 최소 대기 시간. 기본값: 10초

verify는 Graph에 연결하지 않고 로컬 output/archive의 완전성만 검사합니다.
repair는 verify에서 발견한 불완전한 페이지만 Graph에서 다시 받습니다.
init-conversion은 백업 대상 중 Markdown·SilverBullet·RAG에 사용할 노트만 별도로 선택합니다.
login은 Graph 인증 상태를 확인하고, 필요하면 기기 로그인을 시작합니다.
'@ | Write-Host
}

function Resolve-ExportConfigurationPath {
    param([Parameter(Mandatory)][string] $RequestedPath)

    if (Test-Path -LiteralPath $RequestedPath -PathType Leaf) {
        return $RequestedPath
    }

    $defaultPath = Resolve-ProjectPath -Path './.local-config/export.json'
    if ($RequestedPath -eq $defaultPath) {
        $legacyPath = Resolve-ProjectPath -Path './config.local.json'
        if (Test-Path -LiteralPath $legacyPath -PathType Leaf) {
            return $legacyPath
        }
    }
    return $RequestedPath
}

function Resolve-ArchiveOutputRoot {
    param(
        [Parameter(Mandatory)][string] $ConfigPath,
        [string] $OutputOverride
    )

    $outputRootValue = $OutputOverride
    if (-not $outputRootValue -and (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
        try {
            $configuration = Get-Content -LiteralPath $ConfigPath -Raw -Encoding utf8 | ConvertFrom-Json
            if ($configuration.outputRoot) {
                $outputRootValue = [string] $configuration.outputRoot
            }
        }
        catch {
            Write-Warning "설정 파일을 읽지 못해 기본 output 디렉터리를 사용합니다: $($_.Exception.Message)"
        }
    }
    if (-not $outputRootValue) {
        $outputRootValue = './output'
    }
    return Resolve-ProjectPath -Path $outputRootValue
}

function Show-Notebooks {
    param([Parameter(Mandatory)][object[]] $Notebooks)

    for ($index = 0; $index -lt $Notebooks.Count; $index++) {
        Write-Host ('[{0,2}] {1}' -f ($index + 1), $Notebooks[$index].displayName)
    }
}

function Initialize-Configuration {
    param([Parameter(Mandatory)][string] $ConfigPath)

    Connect-OneNoteGraph
    $notebooks = @(Get-OneNoteNotebooks)
    if ($notebooks.Count -eq 0) {
        throw '접근 가능한 OneNote 노트북을 찾지 못했습니다.'
    }

    Write-Host "`n접근 가능한 노트북 $($notebooks.Count)개:`n"
    Show-Notebooks -Notebooks $notebooks
    Write-Host ''
    $selectionText = Read-Host '내보낼 번호를 입력하세요 (예: 1,3,5-8)'
    $selection = @(ConvertFrom-NumberSelection -Selection $selectionText -Maximum $notebooks.Count)

    $selected = foreach ($number in $selection) {
        $notebook = $notebooks[$number - 1]
        [ordered]@{
            id = $notebook.id
            name = $notebook.displayName
        }
    }

    $configuration = [ordered]@{
        outputRoot = './output'
        notebooks = @($selected)
    }
    Write-JsonFile -Path $ConfigPath -Value $configuration

    $checklistPath = Resolve-ProjectPath -Path './output/native-backup-checklist.md'
    $checklistLines = [System.Collections.Generic.List[string]]::new()
    $checklistLines.Add('# OneNote 네이티브 ZIP 백업 체크리스트')
    $checklistLines.Add('')
    $checklistLines.Add('OneNote 웹에서 각 노트북을 우클릭하고 **Export notebook**을 선택합니다.')
    $checklistLines.Add('')
    foreach ($notebook in $selected) {
        $checklistLines.Add("- [ ] $($notebook.name)")
    }
    $checklistLines.Add('')
    $checklistLines.Add("선택한 노트북: $($selected.Count)개")
    $checklistLines.Add('')
    $checklistLines.Add('다운로드 후 ZIP을 열어 노트북 폴더와 `.one` 파일이 있는지 확인합니다.')
    $checklistContent = ($checklistLines -join [Environment]::NewLine) + [Environment]::NewLine
    $checklistParent = Split-Path -Parent $checklistPath
    New-Item -ItemType Directory -Path $checklistParent -Force | Out-Null
    [System.IO.File]::WriteAllText($checklistPath, $checklistContent, [System.Text.UTF8Encoding]::new($false))

    Write-Host "`n$($selected.Count)개 노트북을 선택했습니다."
    foreach ($notebook in $selected) {
        Write-Host "- $($notebook.name)"
    }
    Write-Host "`n설정 저장: $ConfigPath"
    Write-Host "네이티브 백업 체크리스트: $checklistPath"
}

function Initialize-ConversionConfiguration {
    param(
        [Parameter(Mandatory)][string] $ExportConfigPath,
        [Parameter(Mandatory)][string] $CanonicalExportConfigPath,
        [Parameter(Mandatory)][string] $ConversionConfigPath
    )

    if (-not (Test-Path -LiteralPath $ExportConfigPath -PathType Leaf)) {
        throw "백업 설정 파일이 없습니다: $ExportConfigPath`n먼저 'pwsh ./onenote-export.ps1 init'을 실행하세요."
    }

    $exportConfiguration = Get-Content -LiteralPath $ExportConfigPath -Raw -Encoding utf8 | ConvertFrom-Json
    $exportNotebooks = @($exportConfiguration.notebooks)
    if ($exportNotebooks.Count -eq 0) {
        throw '백업 설정에 선택된 노트북이 없습니다.'
    }

    if ($ExportConfigPath -ne $CanonicalExportConfigPath) {
        Write-JsonFile -Path $CanonicalExportConfigPath -Value $exportConfiguration
        Write-Host "기존 백업 설정을 로컬 설정 폴더로 복사했습니다: $CanonicalExportConfigPath"
    }

    $displayNotebooks = foreach ($notebook in $exportNotebooks) {
        [pscustomobject]@{
            id = $notebook.id
            displayName = $notebook.name
        }
    }
    Write-Host "`n백업 설정은 변경하지 않습니다."
    Write-Host "아래는 export.json에 이미 등록된 백업 대상이며, Markdown 변환 후보입니다."
    Write-Host "변환 후보 노트북 $($displayNotebooks.Count)개:`n"
    Show-Notebooks -Notebooks @($displayNotebooks)
    Write-Host ''
    $selectionText = Read-Host '이 중 Markdown·SilverBullet·RAG에 포함할 번호만 입력하세요 (예: 1,3,5-8)'
    $selection = @(ConvertFrom-NumberSelection -Selection $selectionText -Maximum $displayNotebooks.Count)

    $selected = @(
        foreach ($number in $selection) {
            $notebook = $exportNotebooks[$number - 1]
            [ordered]@{
                id = $notebook.id
                name = $notebook.name
            }
        }
    )
    $configuration = [ordered]@{
        schemaVersion = 1
        sourceArchiveRoot = './output/archive'
        outputRoot = './output/markdown'
        notebooks = @($selected)
    }
    Write-JsonFile -Path $ConversionConfigPath -Value $configuration

    $selectedIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    foreach ($notebook in $selected) {
        [void] $selectedIds.Add([string] $notebook.id)
    }
    $backupOnly = @($exportNotebooks | Where-Object { -not $selectedIds.Contains([string] $_.id) })

    $policyPath = Join-Path (Split-Path -Parent $ConversionConfigPath) 'POLICY.md'
    $policyLines = [System.Collections.Generic.List[string]]::new()
    $policyLines.Add('# 로컬 OneNote 변환 정책')
    $policyLines.Add('')
    $policyLines.Add('> 이 파일에는 실제 노트북 이름이 포함됩니다. `.local-config/`는 Git에 커밋하지 않습니다.')
    $policyLines.Add('')
    $policyLines.Add('## 백업 대상 (`export.json`)')
    $policyLines.Add('')
    foreach ($notebook in $exportNotebooks) {
        $policyLines.Add("- $($notebook.name)")
    }
    $policyLines.Add('')
    $policyLines.Add('## Markdown · SilverBullet · RAG 대상 (`markdown.json`)')
    $policyLines.Add('')
    foreach ($notebook in $selected) {
        $policyLines.Add("- $($notebook.name)")
    }
    $policyLines.Add('')
    $policyLines.Add('## 백업 전용 — 변환 및 RAG 제외')
    $policyLines.Add('')
    if ($backupOnly.Count -eq 0) {
        $policyLines.Add('- 없음')
    }
    else {
        foreach ($notebook in $backupOnly) {
            $policyLines.Add("- $($notebook.name)")
        }
    }
    $policyLines.Add('')
    $policyLines.Add('## 강제 규칙')
    $policyLines.Add('')
    $policyLines.Add('- `markdown.json`에 ID가 없는 노트북은 Markdown으로 변환하지 않는다.')
    $policyLines.Add('- SilverBullet에는 `markdown.json`의 노트북만 배포한다.')
    $policyLines.Add('- RAG 색인 전 모든 원본 노트북 ID가 허용 목록에 있는지 검사한다.')
    $policyContent = ($policyLines -join [Environment]::NewLine) + [Environment]::NewLine
    $policyParent = Split-Path -Parent $policyPath
    New-Item -ItemType Directory -Path $policyParent -Force | Out-Null
    [System.IO.File]::WriteAllText($policyPath, $policyContent, [System.Text.UTF8Encoding]::new($false))

    Write-Host "`n변환 대상 $($selected.Count)개를 선택했습니다."
    Write-Host "- 변환 설정: $ConversionConfigPath"
    Write-Host "- 로컬 정책: $policyPath"
    Write-Host "- 백업 전용: $($backupOnly.Count)개"
}

function Invoke-ArchiveExport {
    param(
        [Parameter(Mandatory)][string] $ConfigPath,
        [string] $OutputOverride,
        [switch] $ForceAll
    )

    if (-not (Test-Path -LiteralPath $ConfigPath)) {
        throw "설정 파일이 없습니다: $ConfigPath`n먼저 'pwsh ./onenote-export.ps1 init'을 실행하세요."
    }

    $configuration = Get-Content -LiteralPath $ConfigPath -Raw -Encoding utf8 | ConvertFrom-Json
    $configuredNotebooks = @($configuration.notebooks)
    if ($configuredNotebooks.Count -eq 0) {
        throw '설정 파일에 선택된 노트북이 없습니다.'
    }

    $outputRootValue = if ($OutputOverride) { $OutputOverride } else { [string] $configuration.outputRoot }
    $outputRoot = Resolve-ProjectPath -Path $outputRootValue
    $archiveRoot = Join-Path $outputRoot 'archive'
    $manifestPath = Join-Path $outputRoot 'manifest.json'
    New-Item -ItemType Directory -Path $archiveRoot -Force | Out-Null

    $manifest = [ordered]@{
        schemaVersion = 1
        startedAt = [DateTimeOffset]::UtcNow.ToString('o')
        completedAt = $null
        selectedNotebookCount = $configuredNotebooks.Count
        discoveredNotebookCount = 0
        stats = [ordered]@{
            sections = 0
            pagesDiscovered = 0
            pagesExported = 0
            pagesSkipped = 0
            pagesFailed = 0
            resources = 0
            attachments = 0
            externalMediaReferences = 0
            needsVisualReview = 0
        }
        notebooks = [System.Collections.Generic.List[object]]::new()
        failures = [System.Collections.Generic.List[object]]::new()
    }
    Write-JsonFile -Path $manifestPath -Value $manifest

    Connect-OneNoteGraph
    $availableNotebooks = @(Get-OneNoteNotebooks)
    $availableById = @{}
    foreach ($notebook in $availableNotebooks) {
        $availableById[[string] $notebook.id] = $notebook
    }

    foreach ($configuredNotebook in $configuredNotebooks) {
        $configuredId = [string] $configuredNotebook.id
        if (-not $availableById.ContainsKey($configuredId)) {
            $manifest.failures.Add([ordered]@{
                type = 'notebook-not-found'
                notebookId = $configuredId
                notebookName = $configuredNotebook.name
                error = '선택한 노트북이 현재 계정에서 조회되지 않습니다.'
            })
            Write-JsonFile -Path $manifestPath -Value $manifest
            continue
        }

        $notebook = $availableById[$configuredId]
        $manifest.discoveredNotebookCount++
        $notebookDirectoryName = "$(ConvertTo-SafeName -Name ([string] $notebook.displayName))--$(Get-StableId -Value ([string] $notebook.id) -Length 8)"
        $archiveNotebookPath = Join-Path $archiveRoot $notebookDirectoryName
        New-Item -ItemType Directory -Path $archiveNotebookPath -Force | Out-Null

        try {
            $sections = @(Get-OneNoteNotebookSections -Notebook $notebook)
        }
        catch {
            $manifest.failures.Add([ordered]@{
                type = 'notebook-sections-failed'
                notebookId = $notebook.id
                notebookName = $notebook.displayName
                error = $_.Exception.Message
            })
            Write-Warning "노트북 섹션 조회 실패: $($notebook.displayName) - $($_.Exception.Message)"
            Write-JsonFile -Path $manifestPath -Value $manifest
            continue
        }
        $notebookManifest = [ordered]@{
            id = $notebook.id
            name = $notebook.displayName
            sectionCount = $sections.Count
            pageCount = 0
        }
        $manifest.notebooks.Add($notebookManifest)
        $manifest.stats.sections += $sections.Count
        Write-JsonFile -Path (Join-Path $archiveNotebookPath 'notebook.json') -Value $notebook

        Write-Host "`n==> $($notebook.displayName) ($($sections.Count) sections)"
        foreach ($sectionEntry in $sections) {
            $section = $sectionEntry.Section
            $pathSegments = [System.Collections.Generic.List[string]]::new()
            foreach ($segment in @($sectionEntry.Path)) {
                $pathSegments.Add([string] $segment)
            }
            $sectionDirectoryName = "$(ConvertTo-SafeName -Name ([string] $section.displayName))--$(Get-StableId -Value ([string] $section.id) -Length 8)"
            $pathSegments.Add($sectionDirectoryName)

            $archiveSectionPath = $archiveNotebookPath
            foreach ($segment in $pathSegments) {
                $archiveSectionPath = Join-Path $archiveSectionPath $segment
            }
            New-Item -ItemType Directory -Path $archiveSectionPath -Force | Out-Null
            Write-JsonFile -Path (Join-Path $archiveSectionPath 'section.json') -Value $section

            Write-Host "  -> $($section.displayName)"
            try {
                $pages = @(Get-OneNoteSectionPages -SectionId ([string] $section.id))
            }
            catch {
                $manifest.failures.Add([ordered]@{
                    type = 'section-pages-failed'
                    notebookId = $notebook.id
                    notebookName = $notebook.displayName
                    sectionId = $section.id
                    sectionName = $section.displayName
                    error = $_.Exception.Message
                })
                Write-Warning "섹션 페이지 조회 실패: $($section.displayName) - $($_.Exception.Message)"
                Write-JsonFile -Path $manifestPath -Value $manifest
                continue
            }
            $manifest.stats.pagesDiscovered += $pages.Count
            $notebookManifest.pageCount += $pages.Count

            foreach ($page in $pages) {
                try {
                    $result = Export-OneNotePage `
                        -Page $page `
                        -ArchiveSectionPath $archiveSectionPath `
                        -Force:$ForceAll

                    if ($result.Status -eq 'skipped') {
                        $manifest.stats.pagesSkipped++
                        Write-Host "     [skip] $($page.title)"
                    }
                    else {
                        $manifest.stats.pagesExported++
                        Write-Host "     [done] $($page.title)"
                    }
                    $manifest.stats.resources += $result.ResourceCount
                    $manifest.stats.attachments += $result.AttachmentCount
                    $manifest.stats.externalMediaReferences += $result.ExternalMediaReferenceCount
                    if ($result.NeedsVisualReview) {
                        $manifest.stats.needsVisualReview++
                    }
                }
                catch {
                    $manifest.stats.pagesFailed++
                    $manifest.failures.Add([ordered]@{
                        type = 'page-export-failed'
                        notebookId = $notebook.id
                        notebookName = $notebook.displayName
                        sectionId = $section.id
                        sectionName = $section.displayName
                        pageId = $page.id
                        pageTitle = $page.title
                        error = $_.Exception.Message
                    })
                    Write-Warning "페이지 실패: $($page.title) - $($_.Exception.Message)"
                }
                finally {
                    Write-JsonFile -Path $manifestPath -Value $manifest
                }
            }
        }
    }

    $manifest.completedAt = [DateTimeOffset]::UtcNow.ToString('o')
    Write-JsonFile -Path $manifestPath -Value $manifest

    Write-Host "`n완료"
    Write-Host "- 선택/발견 노트북: $($manifest.selectedNotebookCount)/$($manifest.discoveredNotebookCount)"
    Write-Host "- 페이지 발견: $($manifest.stats.pagesDiscovered)"
    Write-Host "- 새로 보존: $($manifest.stats.pagesExported)"
    Write-Host "- 변경 없음: $($manifest.stats.pagesSkipped)"
    Write-Host "- 실패: $($manifest.stats.pagesFailed)"
    Write-Host "- 외부 미디어 참조: $($manifest.stats.externalMediaReferences)"
    Write-Host "- 시각 검토 필요: $($manifest.stats.needsVisualReview)"
    Write-Host "- manifest: $manifestPath"

    if ($manifest.failures.Count -gt 0 -or $manifest.discoveredNotebookCount -ne $manifest.selectedNotebookCount) {
        exit 2
    }
}

function Invoke-ArchiveVerification {
    param(
        [Parameter(Mandatory)][string] $ConfigPath,
        [string] $OutputOverride
    )

    $outputRoot = Resolve-ArchiveOutputRoot -ConfigPath $ConfigPath -OutputOverride $OutputOverride
    $result = Test-OneNoteArchive -OutputRoot $outputRoot
    $reportPath = Join-Path $outputRoot 'verify-report.json'
    Write-JsonFile -Path $reportPath -Value $result

    Write-Host "`n로컬 아카이브 검증 완료 (Graph API 요청: 0회)"
    Write-Host "- 섹션: $($result.sectionsChecked)"
    Write-Host "- 페이지: $($result.pagesChecked)"
    Write-Host "- 정상: $($result.completePages)"
    Write-Host "- 불완전: $($result.incompletePages)"
    Write-Host "- 보고서: $reportPath"

    foreach ($warning in @($result.warnings)) {
        Write-Warning $warning
    }
    foreach ($issue in @($result.issues)) {
        $displayName = if ($issue.title) { $issue.title } else { '(제목 확인 불가)' }
        Write-Host "`n[incomplete] $displayName"
        Write-Host "  경로: $($issue.path)"
        if (@($issue.missingFiles).Count -gt 0) {
            Write-Host "  누락 파일: $(@($issue.missingFiles) -join ', ')"
        }
        if (@($issue.invalidFiles).Count -gt 0) {
            Write-Host "  손상 파일: $(@($issue.invalidFiles) -join ', ')"
        }
        if (@($issue.missingResources).Count -gt 0) {
            Write-Host "  누락 리소스: $(@($issue.missingResources) -join ', ')"
        }
        if (@($issue.partFiles).Count -gt 0) {
            Write-Host "  미완료 임시 파일: $(@($issue.partFiles) -join ', ')"
        }
    }

    if (-not $result.healthy) {
        exit 2
    }
}

function Invoke-ArchiveRepair {
    param(
        [Parameter(Mandatory)][string] $ConfigPath,
        [string] $OutputOverride
    )

    $outputRoot = Resolve-ArchiveOutputRoot -ConfigPath $ConfigPath -OutputOverride $OutputOverride
    $verification = Test-OneNoteArchive -OutputRoot $outputRoot
    if ($verification.healthy) {
        Write-Host '불완전한 페이지가 없습니다. Graph API를 호출하지 않았습니다.'
        return
    }

    $repairableCount = @($verification.issues | Where-Object pageId).Count
    if ($repairableCount -eq 0) {
        Write-Warning '불완전한 페이지의 OneNote ID를 찾지 못해 자동 복구할 수 없습니다.'
        Write-Warning '전체 export를 다시 실행하면 해당 페이지를 다시 발견할 수 있습니다.'
        exit 2
    }

    Write-Host "불완전한 페이지 $($verification.incompletePages)개 중 ${repairableCount}개만 다시 받습니다."
    Connect-OneNoteGraph
    $result = Repair-OneNoteArchive -OutputRoot $outputRoot
    $reportPath = Join-Path $outputRoot 'repair-report.json'
    Write-JsonFile -Path $reportPath -Value $result

    foreach ($page in @($result.repaired)) {
        Write-Host "[repaired] $($page.title)"
    }
    foreach ($page in @($result.failed)) {
        Write-Warning "복구 실패: $($page.title) - $($page.error)"
    }
    foreach ($page in @($result.unrepairable)) {
        Write-Warning "자동 복구 불가: $($page.title) - $($page.reason)"
    }

    Write-Host "`n복구 완료"
    Write-Host "- 복구 성공: $($result.repairedPages)"
    Write-Host "- 복구 실패: $($result.failedPages)"
    Write-Host "- 자동 복구 불가: $($result.unrepairablePages)"
    Write-Host "- 남은 불완전 페이지: $($result.remainingIncompletePages)"
    Write-Host "- 보고서: $reportPath"

    if ($result.remainingIncompletePages -gt 0) {
        exit 2
    }
}

$requestedConfigPath = Resolve-ProjectPath -Path $Config
$configPath = Resolve-ExportConfigurationPath -RequestedPath $requestedConfigPath
$conversionConfigPath = Resolve-ProjectPath -Path $ConversionConfig
Set-OneNoteRequestInterval -Seconds $RequestIntervalSeconds
switch ($Command) {
    'help' { Show-Help }
    'login' { Connect-OneNoteGraph }
    'list' {
        Connect-OneNoteGraph
        Show-Notebooks -Notebooks @(Get-OneNoteNotebooks)
    }
    'init' { Initialize-Configuration -ConfigPath $requestedConfigPath }
    'init-conversion' {
        Initialize-ConversionConfiguration `
            -ExportConfigPath $configPath `
            -CanonicalExportConfigPath $requestedConfigPath `
            -ConversionConfigPath $conversionConfigPath
    }
    'logout' { Disconnect-OneNoteGraph }
    'export' {
        Invoke-ArchiveExport `
            -ConfigPath $configPath `
            -OutputOverride $Output `
            -ForceAll:$Force
    }
    'verify' {
        Invoke-ArchiveVerification `
            -ConfigPath $configPath `
            -OutputOverride $Output
    }
    'repair' {
        Invoke-ArchiveRepair `
            -ConfigPath $configPath `
            -OutputOverride $Output
    }
}
