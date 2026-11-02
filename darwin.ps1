<#
.SYNOPSIS
  Call one of Darwin's Hoard tools from a terminal or a scheduled agent.
.EXAMPLE
  .\darwin.ps1 darwin_find '{"query":"unslop"}'        # inside PowerShell; from cmd or another process use -ArgsFile
  .\darwin.ps1 darwin_add -ArgsFile add.json       # UTF-8 JSON, for text with accents
  .\darwin.ps1 -List                                # tool names
#>
param(
  [Parameter(Position = 0)][string]$Tool,
  [Parameter(Position = 1)][string]$Json = '{}',
  [string]$ArgsFile,
  [switch]$List,
  [string]$Url = 'http://127.0.0.1:5233'
)
$ErrorActionPreference = 'Stop'
$token = (Get-Content (Join-Path $PSScriptRoot 'data\mcp-token') -Raw).Trim()
$headers = @{ Authorization = "Bearer $token" }
if ($List) { $r = Invoke-RestMethod "$Url/api/agent/tools" -Headers $headers; $items = if ($r.tools) { $r.tools } else { $r }; $items | ForEach-Object { $_.name }; return }
if (-not $Tool) { throw 'Name a tool (or use -List).' }
$body = if ($ArgsFile) { Get-Content $ArgsFile -Raw -Encoding UTF8 } else { $Json }
try { $null = $body | ConvertFrom-Json } catch { throw "Arguments are not valid JSON (from another shell, quotes get lost: use -ArgsFile). Got: $body" }
$payload = '{"name":' + (ConvertTo-Json $Tool) + ',"arguments":' + $body + '}'
$bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
$result = Invoke-RestMethod -Method Post -Uri "$Url/api/agent/call" -Headers $headers -ContentType 'application/json; charset=utf-8' -Body $bytes
$result | ConvertTo-Json -Depth 8
