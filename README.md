# OneNote Markdown Exporter

개인 Microsoft 계정의 OneNote를 macOS에서 읽기 전용으로 보존하고, 이후 Markdown으로 변환하기 위한 exporter입니다.

1단계는 Markdown 변환이 아니라 **OneNote 페이지의 Graph HTML, 자유 배치 좌표, 이미지, 첨부파일과 계층을 빠짐없이 로컬에 보존하는 것**입니다. Markdown은 이 원본을 검증한 다음 별도 단계에서 생성합니다.

> 이 저장소에는 exporter 코드만 보관합니다. 실제 노트, 첨부파일, 인증 정보와 노트북 선택 정보가 담긴 `.local-config/`는 `.gitignore`에 포함되어 있습니다.

## 보존 계층

- 네이티브 백업: OneNote 웹에서 직접 받은 ZIP/`.one` 파일. 재해 복구용이며 exporter 밖에서 보관합니다.
- 이관 원본: 이 exporter가 만드는 HTML, 리소스, 메타데이터와 manifest.
- 활용본: 검증된 이관 원본으로 나중에 만드는 SilverBullet용 Markdown.

후속 Markdown 변환 시 적용할 사용자 규칙은 [Markdown 변환 메모](docs/markdown-conversion-notes.md)에 기록합니다.

Graph HTML은 텍스트 상자와 이미지의 `top`, `left`, `width`, `height` 같은 배치 정보를 포함하지만 OneNote의 네이티브 파일 형식 자체는 아닙니다.

## 요구 사항

- macOS
- Homebrew
- PowerShell 7
- Microsoft Graph PowerShell Authentication 모듈

fish에서 설치합니다.

```fish
./scripts/setup.fish
```

수동 설치:

```fish
brew install powershell
pwsh -NoProfile -Command 'Install-Module Microsoft.Graph.Authentication -Scope CurrentUser'
```

Azure 구독이나 별도의 Entra 앱 등록은 필요하지 않습니다. 로그인할 때 Microsoft Graph PowerShell SDK의 앱을 사용하며 읽기 전용 `Notes.Read` 권한만 요청합니다. macOS에서 Graph SDK의 `CurrentUser` 컨텍스트가 안정적으로 재사용되지 않아, 한 명령에서 한 번만 로그인하는 `Process` 방식을 사용합니다.

## 사용법

### 1. 노트북 조회

```fish
pwsh ./onenote-export.ps1 list
```

브라우저에 표시되는 일회용 코드를 입력하고 개인 Microsoft 계정으로 로그인합니다.

`login`은 인증 흐름만 점검하는 명령입니다. `Process` 로그인은 명령이 끝나면 종료되므로, `export`나 `repair`를 직접 실행해 그 안에서 로그인합니다. 한 번 로그인하면 해당 명령 안의 재시도는 다시 로그인하지 않습니다.

```fish
pwsh ./onenote-export.ps1 login
pwsh ./onenote-export.ps1 logout
```

### 2. 내보낼 노트북 선택

```fish
pwsh ./onenote-export.ps1 init
```

쉼표와 범위를 함께 사용할 수 있습니다. 예: `1,3,5-8`. 선택 결과는 Git에서 제외되는 `.local-config/export.json`에 저장됩니다.

선택한 노트북 이름으로 `output/native-backup-checklist.md`도 생성됩니다. 이 체크리스트를 보면서 [네이티브 ZIP 백업 절차](docs/native-backup.md)를 먼저 진행할 수 있습니다.

기존 `config.local.json`이 있으면 계속 읽을 수 있습니다. 이후 `init-conversion`을 실행하면 `.local-config/export.json`으로 안전하게 복사되며 기존 파일은 삭제하지 않습니다.

### 3. Markdown 변환 대상 별도 선택

백업 대상 중 나중에 Markdown·SilverBullet·RAG에 사용할 노트북만 다시 선택합니다.

```fish
pwsh ./onenote-export.ps1 init-conversion
```

이 명령은 기존 백업 목록을 후보로 보여줄 뿐 `.local-config/export.json`을 변경하지 않습니다. 선택한 하위 목록만 `.local-config/markdown.json`에 저장합니다. 잘못 선택했다면 같은 명령을 다시 실행해 덮어쓸 수 있습니다.

다음 파일은 모두 Git에서 제외됩니다.

```text
.local-config/
├── export.json       # 원본 백업 대상
├── markdown.json     # Markdown·SilverBullet·RAG 허용 대상
├── curation.json     # 자유 배치 검토 후 확정한 비공개 재배치 규칙
└── POLICY.md         # 포함·제외 목록과 로컬 개인정보 정책
```

공개 문서에는 실제 노트북 이름을 적지 않습니다. 후속 변환기는 반드시 `markdown.json`의 OneNote 노트북 ID만 허용하고, 나머지는 기본적으로 거부해야 합니다.

### 4. 원본 보존

```fish
pwsh ./onenote-export.ps1 export
```

OneNote Graph의 공식 한도보다 여유 있게 모든 요청 사이를 기본 10초씩 띄웁니다. `429 / 20166 TooManyRequests`가 발생하면 60초부터 최대 15분까지 지수적으로 쉬고 같은 요청을 계속 재시도하므로 사용자가 다시 실행할 필요가 없습니다.

결과는 기본적으로 `output/`에 생성됩니다.

```text
output/
├── archive/
│   └── <notebook>/<section>/<page-id>/
│       ├── page.raw.html       # Graph 응답 원본
│       ├── page.local.html     # 이미지/첨부 링크를 로컬로 변경한 HTML
│       ├── page.json           # 페이지와 배치 분석 메타데이터
│       ├── layout.json         # 자유 배치 블록의 좌표 목록
│       └── assets/             # 이미지와 첨부파일
└── manifest.json               # 전체 수량과 실패 검증
```

변경되지 않은 페이지는 자동으로 건너뜁니다. 모두 다시 받으려면:

```fish
pwsh ./onenote-export.ps1 export -Force
```

요청 간격은 변경할 수 있지만, 전체 노트북 내보내기에서는 기본값보다 낮추지 않는 것을 권장합니다.

```fish
pwsh ./onenote-export.ps1 export -RequestIntervalSeconds 10
```

## 검증

`output/manifest.json`에는 다음 정보가 기록됩니다.

- 선택한 노트북 수와 실제 발견한 노트북 수
- 섹션 및 페이지 수
- 새로 받은 페이지와 변경되지 않아 건너뛴 페이지 수
- 이미지와 첨부파일 수
- 로컬에 포함되지 않은 외부 미디어와 iframe 참조 수
- 자유 배치 검토가 필요한 페이지 수
- 실패한 페이지와 오류 메시지

각 HTML과 다운로드 리소스의 크기 및 SHA-256이 `page.json`에 기록됩니다.

실행이 중단되어도 다시 `export`하면 완료된 페이지를 재사용합니다. 원격에서 삭제된 페이지의 로컬 파일은 자동으로 삭제하지 않습니다.

### 로컬 완전성 검사

내보내기가 끝난 뒤 다음 명령으로 아카이브를 검사합니다.

```fish
pwsh ./onenote-export.ps1 verify
```

이 명령은 Microsoft Graph에 로그인하거나 API를 호출하지 않습니다. 각 페이지의 `page.raw.html`, `page.local.html`, `layout.json`, `page.json` 존재 여부와 빈 파일·잘못된 JSON·누락된 리소스·로컬 HTML에 남은 OneNote 원격 리소스 URL·남은 `.part` 파일을 로컬에서만 확인합니다. 결과는 화면과 `output/verify-report.json`에 기록되며, 불완전한 페이지가 있으면 종료 코드 `2`를 반환합니다.

다른 출력 경로를 검사하려면:

```fish
pwsh ./onenote-export.ps1 verify -Output /path/to/output
```

불완전한 페이지가 발견되면 전체 노트북을 다시 순회하지 않고 해당 페이지만 복구할 수 있습니다.

```fish
pwsh ./onenote-export.ps1 repair
```

`repair`는 `page.json` 또는 마지막 `manifest.json`에 기록된 OneNote 페이지 ID를 사용합니다. 불완전한 페이지만 Graph에서 다시 받고, 기존 `page.json` 메타데이터와 이미 받은 정상 리소스는 재사용합니다. 결과는 `output/repair-report.json`에 기록됩니다.

첨부파일 하나가 실패해도 `page.raw.html`, `page.local.html`, `layout.json`, `page.json`은 작성하고, `page.json`에 `archiveStatus: incomplete`과 실패한 리소스를 기록합니다. 누락된 파일을 `assets/`에 같은 이름으로 수동 보완한 뒤 `repair`를 다시 실행하면, 파일을 재사용하고 SHA-256을 기록해 완료 상태로 갱신합니다. 원본 페이지 ID가 `404 Not Found`를 반환하는 항목은 삭제·이동·재생성 여부를 확인해야 하는 자동 복구 불가 항목으로 표시합니다.

## Markdown 변환

Markdown 변환은 Graph API나 PowerShell을 사용하지 않으며 macOS·Linux의 fish에서 실행할 수 있습니다. Python 3 표준 라이브러리만 사용합니다.

```fish
./scripts/convert.fish
```

이미 생성한 변환본을 다시 만들려면:

```fish
./scripts/convert.fish --replace
```

`--replace`는 `output/markdown/`에서 직접 수정한 제목 계층과 본문도 다시 생성합니다. 수동 편집을 유지하려면 실행 전에 해당 파일을 백업하거나 `.local-config/curation.json`에 수정 사항을 반영하세요. SilverBullet에 동기화하기 전에도 변경 내용을 비교하세요.

- `.local-config/markdown.json`에 허용된 노트북 ID만 변환하며 나머지는 기본 거부합니다.
- 섹션 그룹·섹션·하위 페이지를 실제 폴더 계층으로 생성합니다.
- `--`로 시작한 이름은 `_old/`로 이동하고 `status: old`, `rag_priority: fallback`을 기록합니다.
- OneNote에서 코드 블록 대신 사용한 1×1 표는 fenced code block으로 변환합니다.
- 문단 하나인 명확한 셸 명령은 인라인 코드로, 연속 명령·heredoc·`\\` 연속행·셸 반복문은
  `bash` 또는 `fish` fenced code block으로 변환합니다. heredoc 안의 `#` 주석은 Markdown 제목이 되지 않습니다.
- 여러 열 표의 명령은 표 구조와 가로 비교를 보존하기 위해 자동 코드 변환에서 제외합니다.
- 이미지와 첨부파일은 페이지 옆 `.assets/`에 복사하고 상대 링크로 연결합니다.
- OneNote 페이지·섹션 링크는 GUID를 대조해 SilverBullet 내부 페이지 링크로 바꿉니다.
- `dnf.conf`, `config.yaml`, `5.2`처럼 확장자로 오인되는 페이지명은 제목은 보존하고 파일명만 `dnf-conf`, `config-yaml`, `5-2` 형태로 바꿉니다.
- 결과와 OneNote ID 매핑은 `output/markdown/_meta/`에 기록합니다.
- `markdown.json`의 `curationFile`이 가리키는 비공개 교정 규칙이 있으면, 자유 배치 박스를 검토 완료된 순서와 형식으로 다시 구성합니다.
- 교정 규칙이 원문의 박스를 빠뜨리거나 존재하지 않는 좌표를 가리키면 변환을 중단합니다. 조용히 내용을 버리지 않습니다.

원본에서 삭제·이동되어 GUID만으로 찾을 수 없는 옛 내부 링크는 비공개
`.local-config/markdown.json`의 `internalLinkOverrides`로 현행 페이지를 지정할 수 있습니다.
키는 원본 링크의 classic OneNote page GUID이고, 값은 변환 출력 루트 기준 `.md` 경로입니다.
페이지 ID가 없는 섹션 링크는 키 앞에 `section:`을 붙입니다.

`silverBulletRoot`에는 변환본을 SilverBullet space 안에서 배치한 경로를 적습니다.
설정하면 모든 내부 페이지 링크를 `/배치경로/페이지` 형태로 생성하므로 공백·괄호가 있는
긴 경로와 서로 다른 섹션 사이의 링크도 모호하지 않게 연결됩니다. 배치 폴더를 옮기면 이
값도 바꾸고 다시 변환합니다.

```json
{
  "silverBulletRoot": "Imported/OneNote",
  "internalLinkOverrides": {
    "00000000-0000-0000-0000-000000000000": "Notebook/Section/Current page.md",
    "section:11111111-1111-1111-1111-111111111111": "Notebook/Section/_index.md"
  }
}
```

변환 결과와 미해결 링크는 `_meta/internal-link-report.md`와
`_meta/internal-link-report.json`에 기록됩니다. 잘못된 override 경로나 출력 밖을
가리키는 경로는 조용히 무시하지 않고 변환을 중단합니다.

명령과 설명이 한 문단에 섞인 경우에도 내용 전체를 `text` 코드 블록으로 보존합니다.
OneNote 개체 구분 문자도 코드 블록 안에서는 줄바꿈으로 복원합니다. heredoc 종료처럼
코드 블록의 범위를 확정할 수 없는 예외만 `_meta/shell-review.md`와
`_meta/shell-review.json`에 기록됩니다.

macOS에서 받은 아카이브를 Linux에서 변환할 때는 `output/`과 함께 다음 로컬 설정을 옮깁니다.

```text
.local-config/
├── markdown.json
└── curation.json
```

`curation.json`에는 OneNote 페이지 ID와 개인 문서 구조가 들어갈 수 있으므로 `output/`과 마찬가지로 공개 Git에 커밋하지 않습니다. `--replace`는 `output/markdown/`만 교체하며 `.local-config/curation.json`은 건드리지 않습니다.

### SilverBullet 탐색용 메타데이터

변환된 일반 페이지에는 원본에서 확실히 알 수 있는 구조 정보만 태그로 추가합니다.

- `source/onenote`, `type/note`
- `notebook/<이름>`, `section/<이름>`
- `status/current` 또는 `status/old`
- `rag/normal` 또는 `rag/fallback`
- `layout/automatic`, `layout/review`, `layout/curated`
- 첨부가 있으면 `has/document`와 `document/image`, `document/pdf`, `document/video`, `document/audio`, `document/attachment`

사용 방법:

- Page Picker에서 `#태그`를 함께 입력해 일반 노트를 좁힙니다.
- Tag Picker는 `Ctrl-Alt-t` 또는 Page Picker의 첫 글자로 `#`을 입력해 엽니다.
- 생성된 노트북·섹션 인덱스와 변환 보고서는 `meta/onenote/...` 태그를 사용하므로 일반 Page Picker에서는 숨고 Meta Picker에서 보입니다. Page Picker의 첫 글자로 `^`를 입력합니다.
- `Navigate: Document Picker`를 실행하면 `.assets/`의 이미지·PDF·영상·첨부파일을 페이지 제목 또는 원본 파일명으로 찾을 수 있습니다.
- 첨부 현황과 확장자별 개수는 `_meta/document-picker.md`에 생성됩니다.
- 실제 태그별 페이지 수와 사용 안내는 `_meta/tag-guide.md`에 생성됩니다.

코드 블록의 경계와 인라인 코드의 둥근 배경·여백은 SilverBullet space 루트의 `STYLES.md`에 있는
`space-style` 블록으로 조정합니다. 예시는
[`examples/silverbullet-code-style.md`](examples/silverbullet-code-style.md)에 있습니다.
이 파일은 `OneNote/markdown/` 밖에 두므로 변환 결과를 다시 동기화해도 유지됩니다.
스타일 변경 후 브라우저에서 `System: Reload`를 실행합니다. CSS 변수는 SilverBullet
클라이언트의 테마 변수이며 Kubernetes ConfigMap이나 컨테이너 환경 변수가 아닙니다.

## 자유 배치와 주석

`layout.json`은 절대 위치 요소의 태그, OneNote ID, 좌표, 크기와 HTML 내 위치를 기록합니다. 단어 옆에 배치한 해설처럼 공간 관계가 의미를 가지는 페이지를 찾는 근거로 사용합니다.

Markdown 변환 단계에서는 가까운 블록과 정렬 관계를 이용해 다음 후보로 재구성합니다.

- 인용문
- `→ 설명` 형태의 주석
- 각주
- 원문 바로 아래의 강조 블록

판단이 애매한 페이지는 자동 확정하지 않고 시각 검토 대상으로 남깁니다.

검토가 끝난 페이지는 `curation.json`에서 원본 박스 좌표를 명시해 순서를 정합니다. 결과 문서에는 `layout_curated: true`, `needs_visual_review: false`가 기록됩니다. 여러 줄 설정을 가로로 비교해야 하는 표는 SilverBullet의 HTML-in-Markdown 지원을 이용해 `<table>`과 `<pre><code>`로 생성합니다.

손글씨와 수식은 글자 모양만으로 판독하지 않습니다. 앞뒤 문장, 식에서의 역할, 전공 분야의 표준 기호와 같은 페이지의 반복 표기를 함께 확인해 `t/τ`, `l/1`, `O/0` 등을 구분합니다. 문맥으로도 하나로 확정할 수 없으면 임의로 정규화하지 않고 원본 이미지를 유지한 채 검토 대상으로 남깁니다.

## 보안

- Graph 권한은 `Notes.Read`만 사용합니다.
- `login`은 인증 모듈 로드와 기기 로그인 흐름을 점검합니다.
- 인증은 해당 pwsh 명령이 끝날 때까지 유지되는 `Process` 방식을 사용합니다. 명령 내부의 429·5xx 재시도는 추가 로그인이 필요하지 않습니다.
- 페이지 본문이나 토큰을 별도 로그에 남기지 않습니다.
- `output/`, `.local-config/`, 기존 `config.local.json`은 커밋하지 않습니다.
