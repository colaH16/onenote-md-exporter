# Code block readability

SilverBullet 2.10용 코드 블록 스타일입니다. 이 파일의 내용을 SilverBullet space 루트의
`STYLES.md`에 넣은 뒤 `System: Reload`를 실행하면 적용됩니다.

```space-style
html[data-theme="light"] {
  --editor-code-background-color: #e8eef5;
  --editor-code-color: #24313f;
  --cola-code-border: #6684a3;
  --cola-code-cap: #a4b8cc;
}

html[data-theme="dark"] {
  --editor-code-background-color: #243140;
  --editor-code-color: #e6edf5;
  --cola-code-border: #8ca9c7;
  --cola-code-cap: #60778e;
}

#sb-editor .sb-line-fenced-code {
  box-sizing: border-box;
  background-color: var(--editor-code-background-color) !important;
  color: var(--editor-code-color);
  border-left: 4px solid var(--cola-code-border);
  border-right: 1px solid var(--cola-code-cap);
  padding-left: 0.75rem;
  padding-right: 0.75rem;
}

#sb-editor .sb-line-fenced-code:not(.sb-line-fenced-code + .sb-line-fenced-code) {
  box-shadow: inset 0 2px 0 var(--cola-code-cap);
  border-radius: 6px 6px 0 0;
}

#sb-editor .sb-line-fenced-code:not(:has(+ .sb-line-fenced-code)) {
  box-shadow: inset 0 -2px 0 var(--cola-code-cap);
  border-radius: 0 0 6px 6px;
}

#sb-editor .sb-line-fenced-code:not(.sb-line-fenced-code + .sb-line-fenced-code):not(:has(+ .sb-line-fenced-code)) {
  box-shadow: inset 0 2px 0 var(--cola-code-cap), inset 0 -2px 0 var(--cola-code-cap);
  border-radius: 6px;
}
```
