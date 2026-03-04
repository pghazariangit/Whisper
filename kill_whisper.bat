@echo off
echo ====================================================
echo      WHISPER DICTATION EMERGENCY KILL SWITCH
echo ====================================================
echo.
echo Terminating all python.exe processes to forcefully
echo release hardware locks (Microphone) and clear GPU VRAM.
echo.
taskkill /F /IM python.exe /T
echo Done.
pause