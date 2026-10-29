' Colemailer - hidden start of bot.py (no console window).
'
' Usage:
'   1) First login must be done in a visible console:
'        scripts\run_windows_visible.bat
'      It asks for the phone, the code from Telegram and the 2FA password and
'      saves the session file. Without that file a hidden start has nowhere to
'      type the code.
'   2) Then run this file, or install autostart once:
'        scripts\install_autostart_windows.bat
'
Option Explicit

Dim fso, sh, scriptDir, rootDir, pyw
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
rootDir = fso.GetParentFolderName(scriptDir)

If Not fso.FileExists(rootDir & "\bot.py") Then
    MsgBox "bot.py not found in " & rootDir & vbCrLf & _
           "Put this script into the scripts folder next to bot.py.", 16, "Colemailer"
    WScript.Quit 1
End If

If Not fso.FileExists(rootDir & "\config.txt") Then
    MsgBox "config.txt not found." & vbCrLf & vbCrLf & _
           "Copy config.example.txt to config.txt and fill api_id / api_hash," & vbCrLf & _
           "or start scripts\run_windows_visible.bat and run:" & vbCrLf & _
           "    python bot.py --auto-api +79991234567", 48, "Colemailer"
    WScript.Quit 1
End If

pyw = "pythonw"
If fso.FileExists(rootDir & "\.venv\Scripts\pythonw.exe") Then
    pyw = rootDir & "\.venv\Scripts\pythonw.exe"
ElseIf fso.FileExists(rootDir & "\venv\Scripts\pythonw.exe") Then
    pyw = rootDir & "\venv\Scripts\pythonw.exe"
End If

sh.CurrentDirectory = rootDir
sh.Run Chr(34) & pyw & Chr(34) & " bot.py", 0, False
