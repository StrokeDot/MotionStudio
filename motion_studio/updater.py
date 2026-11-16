"""Built-in updater.

Every Windows build on GitHub is published as a release named build-N with
MotionStudio-win64.zip. The app knows its own build number (written into
_build.py by the build), asks GitHub for the newest build, downloads the zip,
unpacks it next to the app, and hands over to a small PowerShell script that
waits for the app to close, copies the new files over the old ones and starts
the app again. Your projects, saved effects and stickers live in AppData and
are never touched.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Callable

REPO = 'StrokeDot/MotionStudio'
ASSET = 'MotionStudio-win64.zip'
API = f'https://api.github.com/repos/{REPO}/releases?per_page=15'
USER_AGENT = 'MotionStudio-updater'

try:
    from ._build import BUILD, COMMIT          # written by the Windows build
except Exception:                               # running from source
    BUILD, COMMIT = 0, ''


class Cancelled(Exception):
    pass


@dataclass
class Release:
    build: int
    tag: str
    url: str
    size: int
    notes: str


def current_build() -> int:
    return int(BUILD)


def is_packaged() -> bool:
    return bool(getattr(sys, 'frozen', False))


def parse_releases(data: list) -> Release | None:
    """Newest build-N release that has the Windows zip."""
    best = None
    for r in data or []:
        if r.get('draft'):
            continue
        m = re.fullmatch(r'build-(\d+)', str(r.get('tag_name', '')))
        if not m:
            continue
        asset = next((a for a in r.get('assets') or [] if a.get('name') == ASSET), None)
        if not asset:
            continue
        rel = Release(int(m.group(1)), r['tag_name'], asset['browser_download_url'],
                      int(asset.get('size') or 0), (r.get('body') or '').strip())
        if best is None or rel.build > best.build:
            best = rel
    return best


def fetch_latest(timeout: float = 15.0) -> Release | None:
    req = urllib.request.Request(API, headers={'User-Agent': USER_AGENT,
                                               'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return parse_releases(json.loads(resp.read().decode('utf-8')))


def newer_available(latest: Release | None, build: int | None = None) -> bool:
    build = current_build() if build is None else build
    return latest is not None and latest.build > build


def download(rel: Release, dest: str, progress: Callable[[int, int], bool] | None = None) -> str:
    """Download the zip to `dest`; `progress(done, total)` may return False to cancel."""
    req = urllib.request.Request(rel.url, headers={'User-Agent': USER_AGENT})
    tmp = dest + '.part'
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, 'wb') as out:
        total = int(resp.headers.get('Content-Length') or rel.size or 0)
        done = 0
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress and progress(done, total) is False:
                raise Cancelled()
    if rel.size and os.path.getsize(tmp) != rel.size:
        os.remove(tmp)
        raise RuntimeError('The download was incomplete. Please try again.')
    os.replace(tmp, dest)
    return dest


def app_dir() -> str:
    """Folder that holds MotionStudio.exe (the packaged app)."""
    return os.path.dirname(os.path.abspath(sys.executable))


def stage(zip_path: str, staging_root: str) -> str:
    """Unpack the zip; returns the folder that holds the new MotionStudio.exe."""
    if os.path.isdir(staging_root):
        shutil.rmtree(staging_root, ignore_errors=True)
    os.makedirs(staging_root, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        bad = z.testzip()
        if bad:
            raise RuntimeError(f'The download is damaged ({bad}). Please try again.')
        for name in z.namelist():                     # refuse paths that escape the folder
            target = os.path.realpath(os.path.join(staging_root, name))
            if not target.startswith(os.path.realpath(staging_root) + os.sep) and \
                    target != os.path.realpath(staging_root):
                raise RuntimeError('The download contains unsafe paths.')
        z.extractall(staging_root)
    for root, _dirs, files in os.walk(staging_root):
        if 'MotionStudio.exe' in files:
            return root
    raise RuntimeError('The download does not contain MotionStudio.exe.')


INSTALL_SCRIPT = r'''
param([int]$AppPid, [string]$Src, [string]$Dst, [string]$Exe, [string]$Log, [string]$Cleanup)
function Log($m) { Add-Content -Path $Log -Value ("{0}  {1}" -f (Get-Date -Format s), $m) }
Log "update: waiting for the app (pid $AppPid) to close"
try { Wait-Process -Id $AppPid -Timeout 120 -ErrorAction SilentlyContinue } catch {}
Start-Sleep -Milliseconds 700
# Mirror the new files into the app folder (retries if a file is still busy).
$null = robocopy "$Src" "$Dst" /MIR /R:20 /W:1 /NFL /NDL /NJH /NJS /NP
$code = $LASTEXITCODE
Log "update: copy finished with code $code"
if ($code -ge 8) {
    Log "update: FAILED, starting the existing app"
} else {
    if ($Cleanup) { Remove-Item -Path $Cleanup -Recurse -Force -ErrorAction SilentlyContinue }
}
if (Test-Path $Exe) { Start-Process -FilePath $Exe }
Log "update: done"
'''


def write_install_script(folder: str) -> str:
    path = os.path.join(folder, 'motionstudio-update.ps1')
    with open(path, 'w', encoding='utf-8-sig') as f:
        f.write(INSTALL_SCRIPT)
    return path


def log_path() -> str:
    base = os.environ.get('LOCALAPPDATA') or tempfile.gettempdir()
    d = os.path.join(base, 'MotionStudio')
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, 'update.log')


def launch_installer(new_app_folder: str, cleanup: str = '', target: str | None = None,
                     exe: str | None = None, pid: int | None = None) -> subprocess.Popen:
    """Start the PowerShell script that finishes the update after this app quits."""
    target = target or app_dir()
    exe = exe or os.path.join(target, 'MotionStudio.exe')
    script = write_install_script(tempfile.gettempdir())
    cmd = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
           '-File', script, '-AppPid', str(pid or os.getpid()), '-Src', new_app_folder, '-Dst', target,
           '-Exe', exe, '-Log', log_path(), '-Cleanup', cleanup]
    flags = 0
    if os.name == 'nt':
        flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(cmd, creationflags=flags, close_fds=True)


def staging_root_for(build: int) -> str:
    """Unpack next to the app when possible (same drive, so copying is quick)."""
    parent = os.path.dirname(app_dir())
    cand = os.path.join(parent, f'.MotionStudio-update-{build}')
    try:
        os.makedirs(cand, exist_ok=True)
        probe = os.path.join(cand, '.write-test')
        open(probe, 'w').close()
        os.remove(probe)
        return cand
    except OSError:
        return os.path.join(tempfile.gettempdir(), f'MotionStudio-update-{build}')
