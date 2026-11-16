"""Export: ProRes 4444 .mov with transparency (for Filmora), or a PNG sequence.

Faster export (the approach from StrokeScribe's parallel export): frames do
not depend on each other, so worker processes each get the project once and
render small chunks of frames; the main process writes them in order. If the
workers cannot start, export simply renders on one core.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from typing import Callable

from PySide6.QtGui import QImage

from .timeline import Timeline, render_timeline

FORMATS = {
    'prores': 'ProRes 4444 .mov (transparent, best for Filmora)',
    'png': 'PNG image sequence (transparent)',
}
MIN_PARALLEL_FRAMES = 90
CHUNK = 6
MAX_WORKERS = 8


def find_ffmpeg() -> str:
    """FFmpeg next to the app, then on PATH, then the copy bundled with imageio-ffmpeg."""
    here = os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else __file__)
    for name in ('ffmpeg.exe', 'ffmpeg'):
        cand = os.path.join(here, name)
        if os.path.isfile(cand):
            return cand
    found = shutil.which('ffmpeg')
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:   # pragma: no cover - depends on the machine
        raise RuntimeError('FFmpeg was not found, so ProRes export is unavailable.') from exc


class Cancelled(Exception):
    pass


def worker_count(frames: int) -> int:
    env = os.environ.get('MOTIONSTUDIO_EXPORT_WORKERS')
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    cores = os.cpu_count() or 1
    if frames < MIN_PARALLEL_FRAMES or cores < 3:
        return 1
    return max(1, min(cores - 1, MAX_WORKERS))


def _rgba_bytes(img: QImage) -> bytes:
    """Straight (non-premultiplied) RGBA rows, which is what FFmpeg's "rgba" means."""
    rgba = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h, bpl = rgba.width(), rgba.height(), rgba.bytesPerLine()
    data = bytes(rgba.constBits())
    if bpl == w * 4:
        return data
    return b''.join(data[y * bpl:y * bpl + w * 4] for y in range(h))


# ---------------------------------------------------------------- worker side

_TL: Timeline | None = None


def _worker_init(data: dict):
    global _TL
    from PySide6.QtGui import QGuiApplication
    if QGuiApplication.instance() is None:
        if sys.platform != 'win32':
            os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        _worker_init.app = QGuiApplication([])     # text rendering needs a GUI application
    _TL = Timeline.from_dict(data)


def _render_chunk(frames: list[int]) -> list[bytes]:
    return [_rgba_bytes(render_timeline(_TL, i / _TL.fps)) for i in frames]


# ---------------------------------------------------------------- main side


def _frames_in_order(project: Timeline, total: int, workers: int):
    """Yield (index, rgba bytes) in order, rendering in worker processes when useful."""
    def single(start=0):
        for i in range(start, total):
            yield i, _rgba_bytes(render_timeline(project, i / project.fps))

    if workers <= 1:
        yield from single()
        return
    try:
        # "spawn" everywhere (Windows' only mode): forking a process that already
        # runs Qt can hang the copy.
        import multiprocessing
        pool = ProcessPoolExecutor(max_workers=workers, initializer=_worker_init,
                                   initargs=(project.to_dict(),),
                                   mp_context=multiprocessing.get_context('spawn'))
    except Exception:
        yield from single()
        return
    chunks = [list(range(s, min(total, s + CHUNK))) for s in range(0, total, CHUNK)]
    pending = []
    next_chunk = 0
    produced = 0
    try:
        while produced < total:
            while next_chunk < len(chunks) and len(pending) < workers * 2:
                pending.append(pool.submit(_render_chunk, chunks[next_chunk]))
                next_chunk += 1
            try:
                frames = pending.pop(0).result()
            except Exception:
                # Workers failed: finish the remaining frames on this core.
                pool.shutdown(wait=False, cancel_futures=True)
                yield from single(produced)
                return
            for data in frames:
                yield produced, data
                produced += 1
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def export(project: Timeline, path: str, fmt: str = 'prores',
           progress: Callable[[int, int], bool] | None = None, workers: int | None = None) -> str:
    """Render every frame and write the file. `progress(done, total)` may return
    False to cancel. Returns the written path (a folder for PNG sequences)."""
    total = project.frame_count()
    w, h = project.width, project.height
    workers = worker_count(total) if workers is None else workers
    if fmt == 'png':
        os.makedirs(path, exist_ok=True)
        for i, data in _frames_in_order(project, total, workers):
            QImage(data, w, h, w * 4, QImage.Format.Format_RGBA8888).save(
                os.path.join(path, f'frame_{i:05d}.png'))
            if progress and progress(i + 1, total) is False:
                raise Cancelled()
        return path

    if w % 2 or h % 2:
        raise ValueError('ProRes needs an even width and height.')
    ffmpeg = find_ffmpeg()
    base, ext = os.path.splitext(path)
    tmp = base + '.part' + (ext or '.mov')
    cmd = [ffmpeg, '-y', '-hide_banner', '-loglevel', 'error',
           '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', f'{w}x{h}', '-r', f'{project.fps:g}', '-i', '-',
           '-c:v', 'prores_ks', '-profile:v', '4', '-pix_fmt', 'yuva444p10le',
           '-alpha_bits', '16', '-vendor', 'apl0', tmp]
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
    try:
        for i, data in _frames_in_order(project, total, workers):
            proc.stdin.write(data)
            if progress and progress(i + 1, total) is False:
                raise Cancelled()
        proc.stdin.close()
        err = proc.stderr.read().decode(errors='replace')
        if proc.wait() != 0:
            raise RuntimeError('FFmpeg could not write the video:\n' + err[-1500:])
        os.replace(tmp, path)        # the destination is only replaced by a complete file
    except BaseException:
        proc.kill()
        proc.wait()
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise
    return path
