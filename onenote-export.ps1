#!/usr/bin/env pwsh

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('help', 'list', 'init', 'export')]
    [string] $Command = 'help',

    [string] $Config = './config.local.json',
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
  pwsh ./onenote-export.ps1 list
  pwsh ./onenote-export.ps1 init
  pwsh ./onenote-export.ps1 export [-Force]

옵션:
  -Config <path>   로컬 설정 파일. 기본값: ./config.local.json
  -Output <path>   출력 디렉터리. 설정의 outputRoot보다 우선합니다.
  -Force           변경 여부와 관계없이 모든 페이지를 다시 받습니다.
  -RequestIntervalSeconds <seconds>
                   Graph 요청 사이의 최소 대기 시간. 기본값: 10초
'@ | Write-Host
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

$configPath = Resolve-ProjectPath -Path $Config
Set-OneNoteRequestInterval -Seconds $RequestIntervalSeconds
switch ($Command) {
    'help' { Show-Help }
    'list' {
        Connect-OneNoteGraph
        Show-Notebooks -Notebooks @(Get-OneNoteNotebooks)
    }
    'init' { Initialize-Configuration -ConfigPath $configPath }
    'export' {
        Invoke-ArchiveExport `
            -ConfigPath $configPath `
            -OutputOverride $Output `
            -ForceAll:$Force
    }
}
