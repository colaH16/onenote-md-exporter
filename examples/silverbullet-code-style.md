# Code readability

SilverBullet 2.10용 코드 블록·인라인 코드 스타일입니다. 이 파일의 내용을 SilverBullet space 루트의
`STYLES.md`에 넣은 뒤 `System: Reload`를 실행하면 적용됩니다.

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
  border: 1px solid var(--cola-code-border);
  border-radius: 6px;
  padding: 0.05em 0.5em;
  box-decoration-break: clone;
  -webkit-box-decoration-break: clone;
}
```
