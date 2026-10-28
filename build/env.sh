# Source this from Git Bash to get an x86 MSVC environment without vcvars.
# Finds the newest Visual Studio with the C++ tools (through vswhere) and the newest Windows 10/11 SDK.
# Set MSVC, WK or WKV beforehand to pick a different toolset, SDK folder or SDK version.
PF86="$(cygpath -u "$(printenv 'ProgramFiles(x86)')")"
if [ -z "${MSVC:-}" ]; then
    VS="$("$PF86/Microsoft Visual Studio/Installer/vswhere.exe" -latest -products '*' \
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | tr -d '\r')"
    VS="$(cygpath -u "$VS")"
    MSVC="$VS/VC/Tools/MSVC/$(tr -d '\r\n ' < "$VS/VC/Auxiliary/Build/Microsoft.VCToolsVersion.default.txt")"
fi
WK="${WK:-$PF86/Windows Kits/10}"
if [ -z "${WKV:-}" ]; then
    for v in $(ls "$WK/Lib" | sort -V); do
        [ -f "$WK/Include/$v/um/windows.h" ] && [ -d "$WK/Lib/$v/um/x86" ] && WKV="$v"
    done
fi
w() { cygpath -w "$1"; }
export PATH="$MSVC/bin/HostX64/x86:$MSVC/bin/HostX64/x64:$PATH"
export INCLUDE="$(w "$MSVC/include");$(w "$WK/Include/$WKV/ucrt");$(w "$WK/Include/$WKV/um");$(w "$WK/Include/$WKV/shared")"
export LIB="$(w "$MSVC/lib/x86");$(w "$WK/Lib/$WKV/ucrt/x86");$(w "$WK/Lib/$WKV/um/x86")"
# Stop MSYS from rewriting /flags into paths.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"
