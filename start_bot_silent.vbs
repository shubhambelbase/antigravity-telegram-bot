Set objFSO = CreateObject("Scripting.FileSystemObject")
strDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
Set objShell = CreateObject("WScript.Shell")
objShell.CurrentDirectory = strDir

' Prefer pythonw.exe in virtual environment for 100% windowless execution
If objFSO.FileExists(strDir & "\.venv\Scripts\pythonw.exe") Then
    objShell.Run Chr(34) & strDir & "\.venv\Scripts\pythonw.exe" & Chr(34) & " -m execution.telegram_bot", 0, False
Else
    ' Fallback to run_bot.bat if environment needs initialization
    objShell.Run Chr(34) & strDir & "\run_bot.bat" & Chr(34), 0, False
End If

Set objShell = Nothing
Set objFSO = Nothing
