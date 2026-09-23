# SilverBullet compact style

SilverBullet 2.10용 글자·여백·코드·검색창 스타일입니다. 이 파일의 내용을 SilverBullet space 루트의
`STYLES.md`에 넣은 뒤 `System: Reload`를 실행하면 적용됩니다.
데스크톱에서는 브라우저 확대/축소를 100%로 되돌려 확인하세요.

```space-style
html[data-theme="light"] {
  --editor-code-background-color: #e8eef5;
  --editor-code-color: #24313f;
  --cola-code-border: #6684a3;
}

html[data-theme="dark"] {
  --editor-code-background-color: #243140;
  --editor-code-color: #e6edf5;
  --cola-code-border: #8ca9c7;
}

/* 데스크톱의 글자와 여백을 브라우저 70% 줌에 가깝게 줄입니다. */
@media (min-width: 601px) {
  html {
    font-size: 11.2px !important;
  }

  #sb-main .cm-editor {
    font-size: 12.6px !important;
  }

  #sb-top {
    height: 39px;
  }

  #sb-top .main .inner {
    font-size: 19.6px;
    padding-block: 5.6px;
  }

  #sb-top .main .inner .wrapper {
    padding-inline: 14px;
  }

  .sb-modal-box .sb-header {
    padding: 9px 7px 7px;
  }

  .sb-modal-box .sb-option,
  .sb-modal-box .sb-selected-option {
    padding: 5.6px;
    line-height: 14px;
  }
}

#sb-main .cm-editor .cm-content {
  padding: 3.5px 14px;
}

#sb-main .cm-editor th,
#sb-main .cm-editor td {
  padding: 5.6px;
}

#sb-main .cm-editor thead tr td {
  padding: 7.7px 5.6px;
}

/* 긴 페이지 경로가 줄바꿈되어도 검색 결과를 여러 개 볼 수 있게 합니다. */
@media (min-width: 601px) {
  .sb-modal-box:has(.sb-result-list) {
    width: 1100px;
    max-width: 94vw;
  }
}

.sb-modal-box .sb-result-list {
  max-height: min(68vh, 720px) !important;
}

/* 기본 Page Picker와 Silversearch의 가변 높이 결과를 한 항목씩 구분합니다. */
.sb-modal-box .sb-result-list > .sb-option + .sb-option {
  border-top: 1px solid color-mix(in srgb, currentColor 55%, transparent);
}

#sb-editor .sb-line-fenced-code {
  box-sizing: border-box;
  background-color: var(--editor-code-background-color) !important;
  color: var(--editor-code-color);
  border-left: 1px solid var(--cola-code-border);
  border-right: 1px solid var(--cola-code-border);
  padding-inline: 1.25rem !important;
}

#sb-editor .sb-line-fenced-code:not(.sb-line-fenced-code + .sb-line-fenced-code) {
  box-shadow: inset 0 1px 0 var(--cola-code-border);
  border-radius: 6px 6px 0 0;
}

#sb-editor .sb-line-fenced-code:not(:has(+ .sb-line-fenced-code)) {
  box-shadow: inset 0 -1px 0 var(--cola-code-border);
  border-radius: 0 0 6px 6px;
}

#sb-editor .sb-line-fenced-code:not(.sb-line-fenced-code + .sb-line-fenced-code):not(:has(+ .sb-line-fenced-code)) {
  box-shadow: inset 0 1px 0 var(--cola-code-border), inset 0 -1px 0 var(--cola-code-border);
  border-radius: 6px;
}

#sb-editor .cm-line:not(.sb-line-fenced-code):not(.sb-line-code) .sb-code {
  background-color: var(--editor-code-background-color) !important;
  color: var(--editor-code-color);
  border-radius: 6px;
  padding: 0.05em 0.5em;
  box-decoration-break: clone;
  -webkit-box-decoration-break: clone;
}

/* 모바일 본문도 줄이되, 터치 버튼과 인라인 코드의 별도 스타일은 유지합니다. */
@media (max-width: 600px) {
  #sb-main .cm-editor {
    font-size: 14px !important;
  }

  #sb-top .main .inner {
    font-size: 24px;
    padding-block: 6px;
  }

  #sb-top .main .inner .wrapper {
    padding-inline: 16px;
  }

  #sb-main .cm-editor .cm-content {
    padding: 3.5px 14px;
  }

  #sb-main .cm-editor th,
  #sb-main .cm-editor td {
    padding: 5.25px;
  }

  #sb-main .cm-editor thead tr td {
    padding: 8px 5.25px;
  }

  #sb-editor .sb-line-fenced-code {
    padding-inline: 8px !important;
  }
}
```
