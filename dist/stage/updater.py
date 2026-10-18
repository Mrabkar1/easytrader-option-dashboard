#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EasyTrader Option — Auto-Updater
================================
بررسی GitHub Releases و به‌روزرسانی خودکار نصب استاندارد.

کاربردها:
    python updater.py --check      بررسی + نصب خودکار اگر نسخهٔ جدیدتر باشد (برای راه‌اندازی خودکار)
    python updater.py --force      نصب اجباری آخرین نسخه
    python updater.py --version    نمایش نسخهٔ فعلی
    python updater.py --no-update  (env EASYTRADER_NO_UPDATE=1) غیرفعال کردن کامل

فقط فایل‌های برنامه جایگزین می‌شوند؛ توکن (auth.json)، تنظیمات (config.json)
و لاگ‌ها (server.log) دست‌نخورده می‌مانند.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request as urlrequest
import urllib.error as urlerror
import zipfile

REPO = "Mrabkar1/easytrader-option-dashboard"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
INSTALL_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(INSTALL_DIR, "version.txt")
PRESERVE = {"auth.json", "config.json", "server.log", "version.txt"}  # version.txt توسط نسخهٔ جدید جایگزین می‌شود اما preserve برای ایمنی

def _log(msg):
    try:
        ts = time.strftime("%H:%M:%S")
        print(f"[updater {ts}] {msg}", flush=True)
        with open(os.path.join(INSTALL_DIR, "server.log"), "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [updater] {msg}\n")
    except Exception:
        pass

def current_version() -> str:
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "0.0.0"

def _parse_ver(v: str):
    v = v.strip().lstrip("vV")
    parts = re.findall(r"\d+", v)
    return tuple(int(x) for x in parts) if parts else (0,)

def _newer(remote: str, local: str) -> bool:
    return _parse_ver(remote) > _parse_ver(local)

def latest_release():
    req = urlrequest.Request(API_URL, headers={"User-Agent": "EasyTraderUpdater/1.0",
                                               "Accept": "application/vnd.github+json"})
    with urlrequest.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    tag = data.get("tag_name", "")
    ver = tag.lstrip("vV")
    assets = data.get("assets") or []
    zip_url = None
    for a in assets:
        if a.get("name", "").endswith(".zip"):
            zip_url = a.get("browser_download_url"); break
    return ver, zip_url, tag

def _stop_running():
    try:
        import psutil  # optional
    except Exception:
        psutil = None
    # روش بدون وابستگی: tasklist + taskkill از طریق PowerShell
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='python3.12.exe' OR Name='py.exe'\" | "
         "Where-Object { $_.CommandLine -like '*api_server.py*' -or $_.CommandLine -like '*server.py*' } | "
         "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(2)

def _download(url: str, dest: str) -> bool:
    try:
        req = urlrequest.Request(url, headers={"User-Agent": "EasyTraderUpdater/1.0"})
        with urlrequest.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
            shutil.copyfileobj(resp, f)
        # اعتبارسنجی zip
        with zipfile.ZipFile(dest) as z:
            bad = z.testzip()
            if bad: raise RuntimeError(f"corrupt zip entry: {bad}")
        return True
    except Exception as e:
        _log(f"download failed: {e}")
        return False

def apply_update(zip_path: str) -> bool:
    tmp = tempfile.mkdtemp(prefix="et_update_")
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        # پیدا کردن ریشهٔ استخراج (ممکن است یک پوشهٔ اضافی داشته باشد)
        root = tmp
        entries = os.listdir(tmp)
        if len(entries) == 1 and os.path.isdir(os.path.join(tmp, entries[0])):
            root = os.path.join(tmp, entries[0])

        # پشتیبان‌گیری از فایل‌های فعلی
        backup = os.path.join(INSTALL_DIR, f"backup-pre-update-{int(time.time())}")
        os.makedirs(backup, exist_ok=True)
        for name in os.listdir(INSTALL_DIR):
            src = os.path.join(INSTALL_DIR, name)
            if name in ("auth.json", "config.json", "server.log") or name.startswith("backup-pre-update-"):
                continue
            dst = os.path.join(backup, name)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)

        # جایگزینی فایل‌ها (بدون دست‌کاری auth.json / config.json / server.log)
        for name in os.listdir(root):
            src = os.path.join(root, name)
            dst = os.path.join(INSTALL_DIR, name)
            if name in ("auth.json", "config.json", "server.log"):
                continue
            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        _log("update applied successfully")
        return True
    except Exception as e:
        _log(f"apply failed: {e}")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def _restart():
    runbat = os.path.join(INSTALL_DIR, "run.bat")
    if os.path.exists(runbat):
        try:
            subprocess.Popen(["cmd", "/c", "start", "", runbat],
                             cwd=INSTALL_DIR, creationflags=0x00000008)  # DETACHED_PROCESS
        except Exception as e:
            _log(f"restart failed: {e}")

def check_and_apply(force: bool = False, interactive: bool = False) -> bool:
    if os.environ.get("EASYTRADER_NO_UPDATE", "").lower() in ("1", "true", "yes"):
        return False
    cur = current_version()
    _log(f"checking updates... current={cur}")
    try:
        remote, zip_url, tag = latest_release()
    except Exception as e:
        _log(f"could not reach GitHub: {e}")
        return False
    _log(f"latest release: {remote}  (zip={'yes' if zip_url else 'no'})")
    if not force and not _newer(remote, cur):
        _log("already up to date")
        return False
    if not zip_url:
        _log("no zip asset in release")
        return False

    _log(f"downloading {tag} ...")
    fd, zip_path = tempfile.mkstemp(prefix="et_update_", suffix=".zip")
    os.close(fd)
    if not _download(zip_url, zip_path):
        try: os.remove(zip_path)
        except Exception: pass
        return False

    _log("stopping running server...")
    _stop_running()

    ok = apply_update(zip_path)
    try: os.remove(zip_path)
    except Exception: pass

    if ok:
        # نسخه را ثبت کن
        try:
            with open(VERSION_FILE, "w", encoding="utf-8") as f:
                f.write(remote)
        except Exception: pass
        _log(f"updated to {remote} — restarting")
        _restart()
        return True
    _log("update failed; old files kept in backup-pre-update-*")
    return False

def main():
    ap = argparse.ArgumentParser(description="EasyTrader auto-updater")
    ap.add_argument("--check", action="store_true", help="silent check + auto-apply if newer")
    ap.add_argument("--force", action="store_true", help="force install latest release")
    ap.add_argument("--version", action="store_true", help="print current version")
    args = ap.parse_args()

    if args.version:
        print(current_version()); return
    if args.check or args.force:
        check_and_apply(force=args.force, interactive=args.force)
    else:
        ap.print_help()

if __name__ == "__main__":
    main()
