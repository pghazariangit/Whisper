Set objShell = WScript.CreateObject("WScript.Shell")
objShell.CurrentDirectory = "C:\AG\Whisper"
objShell.Run """C:\AG\Whisper\venv\Scripts\pythonw.exe"" ""C:\AG\Whisper\main.py""", 0, False