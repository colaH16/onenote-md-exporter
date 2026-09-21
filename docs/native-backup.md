# OneNote 네이티브 ZIP 백업

Graph HTML은 이관과 변환을 위한 원본입니다. OneNote 자체 형식의 재해 복구 사본은 별도로 보관합니다.

개인 OneDrive에 저장된 노트북은 OneNote 웹에서 내보낼 수 있습니다.

1. 브라우저에서 [OneNote 웹](https://www.onenote.com/notebooks)에 개인 Microsoft 계정으로 로그인합니다.
2. 대상 노트북을 우클릭합니다.
3. **Export notebook**을 선택합니다.
4. 크기를 확인하고 **Export**를 누릅니다.
5. 다운로드가 끝날 때까지 브라우저를 닫지 않습니다.
6. ZIP 파일을 열어 노트북 폴더와 `.one` 파일이 들어 있는지 확인합니다.
7. `output/native-backup-checklist.md`에서 해당 노트북을 완료 표시합니다.

## 보관 권장 구조

```text
OneNote-native-backup/
├── 2026-09-21/
│   ├── notebook-a.zip
│   ├── notebook-b.zip
│   └── checksums.sha256
└── README.txt
```

ZIP은 SilverBullet 작업 공간이나 exporter Git 저장소에 넣지 않습니다. 별도 백업 위치에 보관하고 가능하면 SHA-256 체크섬도 함께 저장합니다.

## 주의 사항

- 웹 내보내기는 개인 OneDrive 노트북에서만 지원됩니다.
- 큰 노트북은 생성과 다운로드에 시간이 걸릴 수 있습니다.
- 다운로드 중 저장 공간이 부족하면 처음부터 다시 받아야 할 수 있습니다.
- Microsoft의 공식 안내상 내보낸 OneNote 파일을 다시 여는 검증 환경은 Windows OneNote입니다.

공식 안내: [Export OneNote notebooks](https://support.microsoft.com/en-us/onenote/export-and-import-onenote-notebooks)
