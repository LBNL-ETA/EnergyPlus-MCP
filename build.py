"""EnergyPlus-MCP 跨平台打包脚本（PyInstaller）
产出：dist/EnergyPlus-MCP-Windows-x64.exe / -macOS.dmg / -Linux-x86_64.AppImage
"""
import os
import sys
import platform
import shutil
import subprocess

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

ROOT = os.path.dirname(os.path.abspath(__file__))
SYS = platform.system()


def run(cmd):
    print(">>", " ".join(cmd))
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        sys.exit(r.returncode)


def build():
    server_dir = os.path.join(ROOT, "energyplus-mcp-server")
    args = [
        sys.executable, "-m", "PyInstaller",
        "--name", "EnergyPlus-MCP",
        "--noconfirm", "--clean", "--onefile",
        "--paths", server_dir,
        "--add-data", f"gui/web{os.pathsep}gui/web",
        "--collect-all", "energyplus_mcp_server",
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols",
        "--hidden-import", "uvicorn.protocols.http",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan",
        "--hidden-import", "uvicorn.lifespan.on",
        "--hidden-import", "uvicorn.lifespan.off",
        "--hidden-import", "anyio",
        "--hidden-import", "starlette",
        "--hidden-import", "webview",
        "--hidden-import", "webview.platforms.winforms",
        "--hidden-import", "webview.platforms.edgechromium",
        "--hidden-import", "webview.platforms.cocoa",
        "--hidden-import", "webview.platforms.gtk",
        "--collect-all", "fastapi",
    ]
    icon = os.path.join(ROOT, "gui", "assets", "icon.ico") if os.path.exists(os.path.join(ROOT, "gui", "assets", "icon.ico")) else None
    if icon:
        args += ["--icon", icon]
    args += ["gui/app.py"]
    run(args)

    src = os.path.join(ROOT, "dist", "EnergyPlus-MCP" + (".exe" if SYS == "Windows" else ""))
    if SYS == "Windows":
        target = os.path.join(ROOT, "dist", "EnergyPlus-MCP-Windows-x64.exe")
    elif SYS == "Darwin":
        target = os.path.join(ROOT, "dist", "EnergyPlus-MCP-macOS.dmg")
        shutil.move(src, target)
        return target
    else:
        target = os.path.join(ROOT, "dist", "EnergyPlus-MCP-Linux-x86_64.AppImage")
        shutil.move(src, target)
        return target
    shutil.move(src, target)
    return target


if __name__ == "__main__":
    out = build()
    print(f"\nOK: {out} ({os.path.getsize(out)/1024/1024:.1f} MB)")
