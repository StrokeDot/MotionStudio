"""The built-in updater: finding releases, downloading, unpacking, installing."""
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from motion_studio import updater  # noqa: E402


def _rel(tag, build_zip=True, size=10):
    assets = [{'name': updater.ASSET, 'browser_download_url': f'https://x/{tag}.zip', 'size': size}] \
        if build_zip else []
    return {'tag_name': tag, 'assets': assets, 'body': f'notes {tag}', 'draft': False}


def test_picks_the_newest_build_with_a_windows_zip():
    data = [_rel('build-3'), _rel('build-10'), _rel('build-12', build_zip=False), _rel('v1.0'),
            {**_rel('build-11'), 'draft': True}]
    rel = updater.parse_releases(data)
    assert rel.build == 10 and rel.url.endswith('build-10.zip') and rel.notes == 'notes build-10'
    assert updater.newer_available(rel, build=9)
    assert not updater.newer_available(rel, build=10)
    assert updater.parse_releases([]) is None


def _make_zip(path, exe_text='new'):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('MotionStudio/MotionStudio.exe', exe_text)
        z.writestr('MotionStudio/_internal/lib.txt', 'lib')
    return path


def test_download_and_stage(tmp_path):
    src = _make_zip(tmp_path / 'src.zip')
    rel = updater.Release(5, 'build-5', Path(src).as_uri(), os.path.getsize(src), '')
    seen = []
    z = updater.download(rel, str(tmp_path / 'download.zip'), lambda d, t: seen.append(d) or True)
    assert seen and os.path.getsize(z) == rel.size
    folder = updater.stage(z, str(tmp_path / 'files'))
    assert os.path.isfile(os.path.join(folder, 'MotionStudio.exe'))


def test_incomplete_download_is_rejected(tmp_path):
    src = _make_zip(tmp_path / 'src.zip')
    rel = updater.Release(5, 'build-5', Path(src).as_uri(), os.path.getsize(src) + 99, '')
    with pytest.raises(RuntimeError):
        updater.download(rel, str(tmp_path / 'download.zip'))
    assert not os.path.exists(tmp_path / 'download.zip')


def test_unsafe_zip_is_refused(tmp_path):
    bad = tmp_path / 'bad.zip'
    with zipfile.ZipFile(bad, 'w') as z:
        z.writestr('../evil.txt', 'x')
        z.writestr('MotionStudio/MotionStudio.exe', 'x')
    with pytest.raises(RuntimeError):
        updater.stage(str(bad), str(tmp_path / 'files'))


@pytest.mark.skipif(os.name != 'nt', reason='the installer script runs on Windows')
def test_install_script_replaces_the_app_and_restarts_it(tmp_path):
    app = tmp_path / 'MotionStudio'
    (app / '_internal').mkdir(parents=True)
    (app / 'old_only.txt').write_text('old')
    marker = tmp_path / 'started.txt'
    exe = app / 'restart.cmd'
    root = tmp_path / '.update'
    new = root / 'files' / 'MotionStudio'
    (new / '_internal').mkdir(parents=True)
    (new / '_internal' / 'lib.txt').write_text('new lib')
    (new / 'restart.cmd').write_text(f'@echo started> "{marker}"\r\n')
    sleeper = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(2)'])
    proc = updater.launch_installer(str(new), cleanup=str(root), target=str(app), exe=str(exe),
                                    pid=sleeper.pid, detach=False)
    out, _ = proc.communicate(timeout=180)
    log = Path(updater.log_path()).read_text(encoding='utf-8', errors='replace') \
        if os.path.exists(updater.log_path()) else '(no log)'
    info = f'exit {proc.returncode}\n--- output ---\n{out}\n--- log ---\n{log[-3000:]}'
    print(info)
    for _ in range(50):
        if marker.exists():
            break
        time.sleep(0.2)
    assert (app / '_internal' / 'lib.txt').exists(), info
    assert (app / '_internal' / 'lib.txt').read_text() == 'new lib'
    assert not (app / 'old_only.txt').exists()          # mirrored exactly
    assert marker.exists()                               # app started again
    assert not root.exists()                             # download folder cleaned up
