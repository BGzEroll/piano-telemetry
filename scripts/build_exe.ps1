$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$PythonCommand = Get-Command python -ErrorAction SilentlyContinue

if ($null -eq $PythonCommand) {
    throw 'Python not found. Activate the piano-midi environment before building.'
}
$PythonExe = $PythonCommand.Source

& $PythonExe -m PyInstaller --noconfirm --clean "$ProjectRoot\PianoTelemetry.spec"

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

$BuiltExe = "$ProjectRoot\dist\Piano Telemetry.exe"

if (-not ('PianoTelemetry.ShellIconRefresh' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace PianoTelemetry {
    public static class ShellIconRefresh {
        [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
        private static extern void SHChangeNotify(
            uint eventId,
            uint flags,
            string item1,
            IntPtr item2
        );

        public static void Refresh(string path) {
            const uint SHCNE_UPDATEITEM = 0x00002000;
            const uint SHCNF_PATHW = 0x0005;
            SHChangeNotify(SHCNE_UPDATEITEM, SHCNF_PATHW, path, IntPtr.Zero);
        }
    }
}
'@
}

[PianoTelemetry.ShellIconRefresh]::Refresh($BuiltExe)
Write-Host "Built: $BuiltExe"
