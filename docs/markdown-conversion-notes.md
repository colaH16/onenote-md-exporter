# Markdown 변환 메모

이 문서는 HTML 아카이브를 SilverBullet용 Markdown으로 변환할 때 지켜야 할 사용자 규칙을 기록합니다.

## 변환 범위와 개인정보 경계

실제 노트북 이름과 ID, 개인정보 관련 선택 이유는 공개 문서에 기록하지 않습니다. Git에서 제외되는 로컬 설정만 기준으로 삼습니다.

- 백업 범위는 `.local-config/export.json`의 `notebooks`를 확인합니다.
- Markdown·SilverBullet·RAG 변환 허용 범위는 `.local-config/markdown.json`의 `notebooks`만 확인합니다.
- 백업 전용 및 제외 사유는 `.local-config/POLICY.md`를 확인합니다.
- `markdown.json`에 ID가 명시되지 않은 노트북은 기본 거부(default deny)하며 Markdown으로 변환하지 않습니다.
- 백업용 `export.json`의 선택 목록을 변환 허용 목록으로 재사용하지 않습니다.
- `_old/` 및 `rag_priority: fallback` 규칙은 `markdown.json`에 허용된 노트북 내부의 과거 문서에만 적용합니다. 백업 전용 노트북을 `_old/`로 우회 수록하지 않습니다.
- RAG 색인 작업은 입력에 포함된 모든 노트북 ID가 `markdown.json`에 있는지 먼저 검사하고, 하나라도 다르면 전체 작업을 중단해야 합니다.

## 페이지와 섹션 계층

- OneNote의 섹션 그룹과 섹션 계층은 실제 디렉터리 구조로 변환합니다.
- 하위 페이지도 `page.json`의 `order`와 `level`을 이용해 실제 하위 디렉터리 구조로 변환합니다.
- 제목이 같거나 나중에 이름이 바뀌어도 추적할 수 있도록 OneNote ID 매핑은 별도로 보존합니다.

## 코드 블록

- 과거 OneNote에서 코드 블록 대신 1×1 표를 사용했습니다.
- 셀이 하나뿐인 표는 내용을 추측하지 않고 Markdown fenced code block으로 변환합니다.
- 여러 행·여러 열의 표는 일반 Markdown 표로 변환합니다.

## 자유 배치 검토

- 여러 자유 배치 블록이나 펜 입력이 있는 페이지는 `needs_visual_review: true`로 표시합니다.
- 옆에 놓인 짧은 블록을 주석으로 해석한 항목은 `output/markdown/_meta/layout-review.md`에 우선 검토 목록으로 생성합니다.
- 검토 목록에는 변환된 페이지의 해당 위치로 가는 링크, 원래 좌표, 연결 대상으로 추정한 앞 블록과 주석 후보가 포함됩니다.
- 기계적 변환 완료와 사람의 의미 검수 완료는 구분합니다. 검토 목록이 남아 있는 동안 해당 해석은 확정본으로 간주하지 않습니다.
- 검토 목록과 실제 노트 이름은 `output/` 아래에만 생성하며 공개 Git 저장소에 올리지 않습니다.

## 수동 보완한 리소스

- `page.json`에 다운로드 실패로 남아 있어도 `assets/`에 같은 이름의 비어 있지 않은 파일을 수동으로 넣었다면 변환본에서는 완료로 판정합니다.
- 원본 `page.json`의 상태는 `source_archive_status`로, 실제 파일을 확인한 변환 상태는 `archive_status`로 별도 기록합니다.
- `page.local.html`에 Microsoft Graph의 OneNote 리소스 URL이 하나라도 남아 있으면 로컬화되지 않은 자산이므로 incomplete로 판정합니다.
- 이 경우 Markdown에 경고를 넣고 `unlocalized_onenote_resources`에 남은 리소스 수를 기록합니다.

## `--`로 시작하는 이름

- 페이지 또는 섹션 이름이 `--`로 시작하면 과거에 사용하던 방식이며 현재는 사용하지 않는 항목입니다.
- 원본 HTML 아카이브 단계에서는 누락이나 삭제 없이 그대로 보존합니다.
- Markdown 변환 시 제목의 `--`는 제거하고, 가장 가까운 현재 사용 중인 상위 경로 아래의 `_old/` 디렉터리로 이동합니다.
- `--` 섹션의 모든 페이지와 `--` 페이지의 모든 하위 페이지는 old 상태를 상속합니다.
- 원래 OneNote 제목과 ID는 변환 메타데이터에 그대로 보존하여 이름 변경과 충돌을 추적할 수 있어야 합니다.
- old 문서에는 다음 front matter를 추가합니다.

```yaml
status: old
rag_priority: fallback
```

예시:

```text
섹션/
├── 현재 페이지.md
└── _old/
    └── 예전 페이지.md    # 원래 제목: --예전 페이지
```

## RAG 검색 우선순위

- old 문서도 별도 삭제 없이 벡터화하되 `status=old`, `rag_priority=fallback` 메타데이터를 함께 저장합니다.
- 1차 검색은 현재 문서(`status != old`)만 대상으로 합니다.
- 현재 문서에서 충분한 답을 찾지 못한 경우에만 old 문서를 2차로 검색합니다.
- old 검색 결과를 답변에 사용했다면 오래된 자료라는 사실을 사용자에게 표시합니다.
- 운영 설정으로 old 문서의 색인을 완전히 제외할 수 있게 합니다. 기본 정책은 완전 제외가 아니라 후순위 검색입니다.
- 단순 유사도 감점만 사용하지 않습니다. 유사도가 높은 오래된 답이 현재 답보다 먼저 선택되는 일을 막기 위해 현재/old 검색 단계를 분리합니다.
