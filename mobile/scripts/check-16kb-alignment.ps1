param(
  [string]$Apk = "D:\aipd\mobile\android\app\build\outputs\apk\release\app-release.apk",
  [string]$Abi = "arm64-v8a"
)
$re = "C:\Users\HP\AppData\Local\Android\Sdk\ndk\28.2.13676358\toolchains\llvm\prebuilt\windows-x86_64\bin\llvm-readelf.exe"
$tmp = "C:\Users\HP\AppData\Local\Temp\opencode\aligncheck"
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
Copy-Item $Apk "$tmp\app.apk" -Force
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead("$tmp\app.apk")
foreach ($e in $zip.Entries | Where-Object { $_.FullName -like "lib/$Abi/*.so" }) {
  $dest = Join-Path $tmp $e.FullName.Replace("/", "\")
  New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
  [System.IO.Compression.ZipFileExtensions]::ExtractToFile($e, $dest, $true)
}
$zip.Dispose()

$bad = @()
$all = Get-ChildItem "$tmp\lib\$Abi" -Filter *.so
foreach ($so in $all) {
  $aligns = @()
  foreach ($line in (& $re -l $so.FullName 2>$null)) {
    if ($line -match '^\s*LOAD\s.*\s(0x[0-9a-fA-F]+)\s*$') { $aligns += [Convert]::ToInt32($matches[1].Substring(2), 16) }
  }
  $min = if ($aligns.Count) { ($aligns | Measure-Object -Minimum).Minimum } else { 0 }
  $kb = [math]::Round($min / 1024, 2)
  $ok = $min -ge 16384
  if (-not $ok) { $bad += [pscustomobject]@{ lib = $so.Name; minAlign = "$kb KB" } }
}
Write-Output "ABI: $Abi  total .so: $($all.Count)"
if ($bad.Count -eq 0) {
  Write-Output "ALL LIBS 16 KB ALIGNED - OK for Android 15+ devices with 16 KB pages"
} else {
  Write-Output "NOT 16 KB ALIGNED ($($bad.Count) libs):"
  $bad | ForEach-Object { Write-Output ("  " + $_.lib + "  " + $_.minAlign) }
}
