# OneNote Markdown Exporter

개인 Microsoft 계정의 OneNote를 macOS에서 읽기 전용으로 보존하고, 이후 Markdown으로 변환하기 위한 exporter입니다.

1단계는 Markdown 변환이 아니라 **OneNote 페이지의 Graph HTML, 자유 배치 좌표, 이미지, 첨부파일과 계층을 빠짐없이 로컬에 보존하는 것**입니다. Markdown은 이 원본을 검증한 다음 별도 단계에서 생성합니다.

> 이 저장소에는 exporter 코드만 보관합니다. 실제 노트, 첨부파일, 인증 정보와 `config.local.json`은 `.gitignore`에 포함되어 있습니다.

## 보존 계층

- 네이티브 백업: OneNote 웹에서 직접 받은 ZIP/`.one` 파일. 재해 복구용이며 exporter 밖에서 보관합니다.
- 이관 원본: 이 exporter가 만드는 HTML, 리소스, 메타데이터와 manifest.
- 활용본: 검증된 이관 원본으로 나중에 만드는 SilverBullet용 Markdown.

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

Azure 구독이나 별도의 Entra 앱 등록은 필요하지 않습니다. 로그인할 때 Microsoft Graph PowerShell SDK의 앱을 사용하며 읽기 전용 `Notes.Read` 권한만 요청합니다.

## 사용법

### 1. 노트북 조회

```fish
pwsh ./onenote-export.ps1 list
```

브라우저에 표시되는 일회용 코드를 입력하고 개인 Microsoft 계정으로 로그인합니다.

### 2. 내보낼 노트북 선택

```fish
pwsh ./onenote-export.ps1 init
```

쉼표와 범위를 함께 사용할 수 있습니다. 예: `1,3,5-8`. 선택 결과는 Git에서 제외되는 `config.local.json`에 저장됩니다.

선택한 노트북 이름으로 `output/native-backup-checklist.md`도 생성됩니다. 이 체크리스트를 보면서 [네이티브 ZIP 백업 절차](docs/native-backup.md)를 먼저 진행할 수 있습니다.

### 3. 원본 보존

```fish
pwsh ./onenote-export.ps1 export
```

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
- 로그인 컨텍스트는 현재 PowerShell 프로세스에만 유지됩니다.
- 페이지 본문이나 토큰을 별도 로그에 남기지 않습니다.
- `output/`과 `config.local.json`은 커밋하지 않습니다.
