@echo off
setlocal
rem Starts everything for generating the map's AI navmesh (README: "The AI navmesh").
rem   1. Copies the empty mission and its server config into the DayZ game folder.
rem   2. Starts a local DayZ Diag server on the map, with the navmesh data server on.
rem   3. Once you press a key, starts DayZ Tools' NavMeshGenerator. In it:
rem      Generation > Connect Data Server, then Generation > Start generation, and at
rem      100%: File > Save NavMesh as P:\greatsmokymountains\navmesh\navmesh.nm
rem Then close both and repack the map: the navmesh packs inside greatsmokymountains.pbo.

set "DAYZ=G:\SteamLibrary\steamapps\common\DayZ"
set "GEN=G:\SteamLibrary\steamapps\common\DayZ Tools\Bin\NavMeshGenerator\NavMeshGenerator_x64.exe"
set "MOD=G:\SteamLibrary\steamapps\common\DayZ\@greatsmokymountains"
set "HERE=%~dp0"

if not exist "%DAYZ%\DayZDiag_x64.exe" (
    echo DayZDiag_x64.exe isn't in %DAYZ%
    goto :fail
)
if not exist "%GEN%" (
    echo NavMeshGenerator isn't at %GEN%
    goto :fail
)
if not exist "%MOD%\Addons\greatsmokymountains.pbo" (
    echo The map isn't built, or the P: drive isn't mounted: no %MOD%\Addons\greatsmokymountains.pbo
    goto :fail
)
tasklist /fi "imagename eq DayZServer_x64.exe" | find /i "DayZServer_x64.exe" >nul
if not errorlevel 1 (
    echo A DayZ server is running. Stop it first: it would use the same port.
    goto :fail
)

echo Copying the empty mission and its server config into %DAYZ%
xcopy /e /i /y /q "%HERE%empty.greatsmokymountains" "%DAYZ%\mpmissions\empty.greatsmokymountains" >nul || goto :fail
copy /y "%HERE%ServerDZNV.cfg" "%DAYZ%\ServerDZNV.cfg" >nul || goto :fail
if not exist "P:\greatsmokymountains\navmesh" mkdir "P:\greatsmokymountains\navmesh"
if not exist "%TEMP%\gsm_navmesh_server" mkdir "%TEMP%\gsm_navmesh_server"

echo Starting the DayZ Diag server with the navmesh data server...
pushd "%DAYZ%"
start "DayZ Diag navmesh server" DayZDiag_x64.exe -server -mod=%MOD% -startNavmeshDataServer -port=2302 -config=ServerDZNV.cfg -profiles=%TEMP%\gsm_navmesh_server -dologs -adminlog
popd

echo.
echo If Windows asks whether to allow DayZDiag_x64 through the firewall, allow it.
echo Give the server a minute or two to load the map, then press a key here to
echo start NavMeshGenerator.
pause >nul
start "" "%GEN%"
echo.
echo NavMeshGenerator is starting. In it:
echo   1. Generation ^> Connect Data Server   (its log should say it connected)
echo   2. Generation ^> Start generation, and confirm
echo   3. Wait for 100%%. Don't close it.
echo   4. File ^> Save NavMesh: P:\greatsmokymountains\navmesh\navmesh.nm
echo Then close NavMeshGenerator and the server window, and repack the map (it packs inside greatsmokymountains.pbo).
echo.
pause
exit /b 0

:fail
echo.
echo Nothing was started.
pause
exit /b 1
