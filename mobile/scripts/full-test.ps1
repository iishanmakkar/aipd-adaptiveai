$adb="C:\Users\HP\AppData\Local\Android\Sdk\platform-tools\adb.exe"
function Tap($x,$y){ & $adb -s emulator-5554 shell input tap $x $y; Start-Sleep -Milliseconds 1200 }
function Dump($label){ & $adb -s emulator-5554 shell uiautomator dump /sdcard/ui.xml | Out-Null; & $adb -s emulator-5554 pull /sdcard/ui.xml D:\aipd\mobile\ui-test.xml | Out-Null; $t=Get-Content D:\aipd\mobile\ui-test.xml -Raw; $found=@(); foreach($w in @("AdaptiveAI","Read screen","Read aloud","Screenshot","Share screen","OCR text","Detect objects","Type a task","Book a bus","Order groceries","Identify a product","Send emergency","Scan product","Care circle","Emergency voice notes","Tasks","Settings","GOOGLE GEMINI","Save key","Test","Microphone","Accessibility","Speak responses","About you","Saved details","Teach AdaptiveAI","GEMINI")){ if($t -match [regex]::Escape($w)){ $found+=$w } }; Write-Output "=== $label ==="; Write-Output ($found -join ", ") }

Write-Output "TEST START"
Tap 270 2280; Dump "Screen tab"
Tap 450 2280; Dump "Shopping tab"
Tap 630 2280; Dump "Tools tab"
Tap 810 2280; Dump "Tasks tab"
Tap 990 2280; Dump "Settings tab"
Tap 90 2280; Dump "Assistant tab"
Write-Output "TABS DONE"
# Go to Screen tab again and tap Read screen
Tap 270 2280; Dump "Screen again"
# Tap Read screen button (approx 116, 269 -> center)
Tap 116 269; Dump "After Read screen tap"
Tap 270 2280; Write-Output "DONE"
