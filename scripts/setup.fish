#!/usr/bin/env fish

if not type -q brew
    echo "Homebrew가 필요합니다: https://brew.sh" >&2
    exit 1
end

if not type -q pwsh
    echo "PowerShell을 설치합니다."
    brew install powershell; or exit 1
end

echo "Microsoft Graph 인증 모듈을 확인합니다."
pwsh -NoProfile -Command '
  if (-not (Get-Module -ListAvailable Microsoft.Graph.Authentication)) {
    Install-Module Microsoft.Graph.Authentication -Scope CurrentUser
  }
'; or exit 1

echo "준비가 끝났습니다."
echo "다음 명령: pwsh ./onenote-export.ps1 init"
