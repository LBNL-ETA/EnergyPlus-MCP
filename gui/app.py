"""EnergyPlus-MCP Desktop GUI — 图形化界面入口
功能：EnergyPlus 环境检测、配置管理、MCP 服务启停、模拟快速验证

用法：
  python gui/app.py            # 桌面窗口
  python gui/app.py --browser  # 浏览器模式
"""
import os
import sys
import json
import threading
import webbrowser
import subprocess
from pathlib import Path

PORT = int(os.environ.get("EPMCP_PORT", "8631"))
ROOT = Path(__file__).resolve().parents[1]

# ---------- EnergyPlus 自动检测 ----------
def detect_energyplus():
    """检测常见 EnergyPlus 安装位置"""
    candidates = []
    home = str(Path.home())
    for p in [
        r"C:\EnergyPlusV26-1-0", r"C:\EnergyPlusV25-1-0", r"C:\EnergyPlusV24-2-0",
        r"C:\EnergyPlusV23-2-0", r"C:\EnergyPlusV22-2-0", r"C:\EnergyPlus",
        r"D:\EnergyPlus", r"D:\EnergyPlusV26-1-0",
        "/usr/local/EnergyPlus-26-1-0", "/usr/local/EnergyPlus",
        os.path.join(home, "EnergyPlus"),
    ]:
        if os.path.isdir(p):
            exe = None
            for name in ("energyplus.exe", "energyplus"):
                c = os.path.join(p, name)
                if os.path.exists(c):
                    exe = c
                    break
            idd = os.path.join(p, "Energy+.idd")
            candidates.append({"path": p, "executable": exe, "idd": idd if os.path.exists(idd) else ""})
    return candidates


def load_cfg():
    p = ROOT / "gui" / "config.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_cfg(cfg):
    (ROOT / "gui" / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- FastAPI ----------
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

app = FastAPI(title="EnergyPlus-MCP GUI", version="0.2.0")


class ConfigIn(BaseModel):
    installation_path: str = ""
    executable_path: str = ""
    idd_path: str = ""
    weather_path: str = ""
    port: int = 8631


@app.get("/api/status")
def status():
    cfg = load_cfg()
    detections = detect_energyplus()
    ep_ok = bool(cfg.get("executable_path") and os.path.exists(cfg.get("executable_path", "")))
    health = None
    # 探测 MCP server 健康
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{cfg.get('port', PORT)}/health", timeout=3) as r:
            health = json.loads(r.read())
    except Exception:
        health = None
    return {
        "detected": detections,
        "configured": cfg,
        "energyplus_ready": ep_ok,
        "mcp_health": health,
        "mcp_running": health is not None,
    }


@app.post("/api/config")
def set_config(body: ConfigIn):
    cfg = body.model_dump()
    save_cfg(cfg)
    return {"ok": True, "config": cfg}


@app.post("/api/start-mcp")
def start_mcp():
    """后台线程启动 MCP HTTP server"""
    global _mcp_thread
    cfg = load_cfg()
    port = cfg.get("port", PORT)
    try:
        # 确保 energyplus_mcp_server 可导入
        server_dir = str(ROOT / "energyplus-mcp-server")
        if server_dir not in sys.path:
            sys.path.insert(0, server_dir)

        from energyplus_mcp_server.server import mcp, config
        from energyplus_mcp_server.http_app import build_app
        import uvicorn

        config.transport.transport = "streamable-http"
        config.transport.http_host = "127.0.0.1"
        config.transport.http_port = port

        # 应用用户配置（EnergyPlus 路径等）
        for key in ("installation_path", "executable_path", "idd_path", "weather_path"):
            if cfg.get(key):
                setattr(config.energyplus, key, cfg[key])

        app_obj = build_app(mcp, config)

        def _run():
            uvicorn.run(app_obj, host="127.0.0.1", port=port, log_level="warning")

        _mcp_thread = threading.Thread(target=_run, daemon=True)
        _mcp_thread.start()
        return {"ok": True, "port": port}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/tools")
def tools():
    """列出 MCP server 提供的工具能力"""
    try:
        from energyplus_mcp_server.energyplus_tools import EnergyPlusManager
        methods = [m for m in dir(EnergyPlusManager) if not m.startswith("_")]
        return {"tools": methods, "count": len(methods)}
    except Exception as e:
        return {"tools": [], "count": 0, "error": str(e)}


@app.post("/api/verify")
def verify():
    """验证 EnergyPlus 安装可用性"""
    cfg = load_cfg()
    exe = cfg.get("executable_path", "")
    if not exe or not os.path.exists(exe):
        return {"ok": False, "message": "未找到 EnergyPlus 可执行文件，请在配置中设置"}
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=15)
        out = (r.stdout or r.stderr or "").strip()
        return {"ok": True, "version": out[:200]}
    except Exception as e:
        return {"ok": False, "message": str(e)}


# ---------- 静态页面 ----------
web_dir = ROOT / "gui" / "web"


@app.get("/")
def index():
    return FileResponse(web_dir / "index.html")


# ---------- 桌面入口 ----------
def run_server():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


def main():
    threading.Thread(target=run_server, daemon=True).start()
    url = f"http://127.0.0.1:{PORT}"
    if "--browser" in sys.argv:
        webbrowser.open(url)
        print(f"EnergyPlus-MCP GUI: {url}")
        import time
        while True:
            time.sleep(3600)
        return
    try:
        import webview
        webview.create_window("EnergyPlus-MCP 图形界面", url, width=1000, height=720,
                              min_size=(800, 600), background_color="#f5f5f7")
        webview.start()
    except Exception as e:
        print(f"桌面模式失败({e})，浏览器模式: {url}")
        webbrowser.open(url)
        import time
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
