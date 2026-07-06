Option Explicit

Dim fso
Dim shell
Dim scriptDir
Dim appDir
Dim pythonExe
Dim launcherPy
Dim command

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
appDir = fso.GetParentFolderName(scriptDir)
pythonExe = fso.BuildPath(appDir, "python\pythonw.exe")
launcherPy = fso.BuildPath(appDir, "desktop\launcher.py")

If Not fso.FileExists(pythonExe) Then
    MsgBox "Job Hunter Agent is missing its bundled Python runtime." & vbCrLf & vbCrLf & _
        "Expected file:" & vbCrLf & pythonExe & vbCrLf & vbCrLf & _
        "Try re-running the installer.", _
        vbCritical, "Job Hunter Agent"
    WScript.Quit 1
End If

If Not fso.FileExists(launcherPy) Then
    MsgBox "Job Hunter Agent launcher is missing." & vbCrLf & vbCrLf & _
        "Expected file:" & vbCrLf & launcherPy, vbCritical, "Job Hunter Agent"
    WScript.Quit 1
End If

shell.CurrentDirectory = appDir
' Launch through the bundled Python so the desktop shortcut stays self-contained.
command = Chr(34) & pythonExe & Chr(34) & " " & Chr(34) & launcherPy & Chr(34)
shell.Run command, 0, False
