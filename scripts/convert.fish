#!/usr/bin/env fish

set project_root (path resolve (dirname (status filename))/..)

if not type -q python3
    echo "python3가 필요합니다." >&2
    exit 1
end

python3 "$project_root/src/onenote_to_markdown.py" $argv
