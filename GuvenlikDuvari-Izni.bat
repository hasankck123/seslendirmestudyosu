@echo off
setlocal
cd /d "%~dp0"

rem ---- Yonetici yetkisi yoksa yeniden baslat ----
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Yonetici izni isteniyor, lutfen gelen pencereye "Evet" de...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo.
echo  Seslendirme Studyosu - guvenlik duvari izni (Tailscale icin)
echo  -----------------------------------------------------------
echo.

netsh advfirewall firewall delete rule name="Seslendirme Studyosu (Tailscale)" >nul 2>&1
netsh advfirewall firewall add rule name="Seslendirme Studyosu (Tailscale)" ^
    dir=in action=allow protocol=TCP localport=8770 remoteip=100.64.0.0/10 profile=private,domain >nul

if %errorlevel% equ 0 (
    echo  TAMAM: Telefondan Tailscale ile erisim icin izin eklendi.
) else (
    echo  HATA: Kural eklenemedi ^(yonetici izni gerekli^).
)
echo.
pause
