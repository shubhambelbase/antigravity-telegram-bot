Set objFSO = CreateObject("Scripting.FileSystemObject")
strSetupDir = objFSO.GetParentFolderName(WScript.ScriptFullName)

' Resolve project root (parent directory of setup/)
If objFSO.FolderExists(strSetupDir & "\.venv") Then
    strRoot = strSetupDir
Else
    strRoot = objFSO.GetParentFolderName(strSetupDir)
End If

Set objShell = CreateObject("WScript.Shell")
objShell.CurrentDirectory = strRoot

' Prefer pythonw.exe in virtual environment for 100% windowless execution
If objFSO.FileExists(strRoot & "\.venv\Scripts\pythonw.exe") Then
    objShell.Run Chr(34) & strRoot & "\.venv\Scripts\pythonw.exe" & Chr(34) & " -m execution.telegram_bot", 0, False
Else
    ' Fallback to run_bot.bat if environment needs initialization
    objShell.Run Chr(34) & strRoot & "\setup\run_bot.bat" & Chr(34), 0, False
End If

Set objShell = Nothing
Set objFSO = Nothing
