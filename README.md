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

이 명령은 Microsoft Graph에 로그인하거나 API를 호출하지 않습니다. 각 페이지의 `page.raw.html`, `page.local.html`, `layout.json`, `page.json` 존재 여부와 빈 파일·잘못된 JSON·누락된 리소스·남은 `.part` 파일을 로컬에서만 확인합니다. 결과는 화면과 `output/verify-report.json`에 기록되며, 불완전한 페이지가 있으면 종료 코드 `2`를 반환합니다.

다른 출력 경로를 검사하려면:

```fish
pwsh ./onenote-export.ps1 verify -Output /path/to/output
```

불완전한 페이지가 발견되면 전체 노트북을 다시 순회하지 않고 해당 페이지만 복구할 수 있습니다.

```fish
pwsh ./onenote-export.ps1 repair
```

`repair`는 `page.json` 또는 마지막 `manifest.json`에 기록된 OneNote 페이지 ID를 사용합니다. 불완전한 페이지만 Graph에서 다시 받고, 이미 받은 정상 리소스는 재사용합니다. 결과는 `output/repair-report.json`에 기록됩니다.

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

- `.local-config/markdown.json`에 허용된 노트북 ID만 변환하며 나머지는 기본 거부합니다.
- 섹션 그룹·섹션·하위 페이지를 실제 폴더 계층으로 생성합니다.
- `--`로 시작한 이름은 `_old/`로 이동하고 `status: old`, `rag_priority: fallback`을 기록합니다.
- OneNote에서 코드 블록 대신 사용한 1×1 표는 fenced code block으로 변환합니다.
- 이미지와 첨부파일은 페이지 옆 `.assets/`에 복사하고 상대 링크로 연결합니다.
- 결과와 OneNote ID 매핑은 `output/markdown/_meta/`에 기록합니다.

## 자유 배치와 주석

`layout.json`은 절대 위치 요소의 태그, OneNote ID, 좌표, 크기와 HTML 내 위치를 기록합니다. 단어 옆에 배치한 해설처럼 공간 관계가 의미를 가지는 페이지를 찾는 근거로 사용합니다.

Markdown 변환 단계에서는 가까운 블록과 정렬 관계를 이용해 다음 후보로 재구성합니다.

- 인용문
- `→ 설명` 형태의 주석
- 각주
- 원문 바로 아래의 강조 블록

판단이 애매한 페이지는 자동 확정하지 않고 시각 검토 대상으로 남깁니다.

## 보안

- Graph 권한은 `Notes.Read`만 사용합니다.
- `login`은 인증 모듈 로드와 기기 로그인 흐름을 점검합니다.
- 인증은 해당 pwsh 명령이 끝날 때까지 유지되는 `Process` 방식을 사용합니다. 명령 내부의 429·5xx 재시도는 추가 로그인이 필요하지 않습니다.
- 페이지 본문이나 토큰을 별도 로그에 남기지 않습니다.
- `output/`, `.local-config/`, 기존 `config.local.json`은 커밋하지 않습니다.
