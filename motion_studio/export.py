"""Export: ProRes 4444 .mov with transparency (for Filmora), or a PNG sequence."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Callable

from PySide6.QtGui import QImage

from .timeline import Timeline, render_timeline

FORMATS = {
    'prores': 'ProRes 4444 .mov (transparent, best for Filmora)',
    'png': 'PNG image sequence (transparent)',
}


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


def _rgba_bytes(img: QImage) -> bytes:
    # Straight (non-premultiplied) RGBA, which is what FFmpeg's "rgba" means.
    # Keep the converted image alive while its memory is copied.
    rgba = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h, bpl = rgba.width(), rgba.height(), rgba.bytesPerLine()
    data = bytes(rgba.constBits())
    if bpl == w * 4:
        return data
    return b''.join(data[y * bpl:y * bpl + w * 4] for y in range(h))


def export(project: Timeline, path: str, fmt: str = 'prores',
           progress: Callable[[int, int], bool] | None = None) -> str:
    """Render every frame and write the file. `progress(done, total)` may return
    False to cancel. Returns the written path (a folder for PNG sequences)."""
    total = project.frame_count()
    w, h = project.width, project.height
    if fmt == 'png':
        os.makedirs(path, exist_ok=True)
        for i in range(total):
            render_timeline(project, i / project.fps).save(os.path.join(path, f'frame_{i:05d}.png'))
            if progress and progress(i + 1, total) is False:
                raise Cancelled()
        return path

    if w % 2 or h % 2:
        raise ValueError('ProRes needs an even width and height.')
    ffmpeg = find_ffmpeg()
    cmd = [ffmpeg, '-y', '-hide_banner', '-loglevel', 'error',
           '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', f'{w}x{h}', '-r', f'{project.fps:g}', '-i', '-',
           '-c:v', 'prores_ks', '-profile:v', '4', '-pix_fmt', 'yuva444p10le',
           '-alpha_bits', '16', '-vendor', 'apl0', '-movflags', '+write_colr', path]
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
    try:
        for i in range(total):
            proc.stdin.write(_rgba_bytes(render_timeline(project, i / project.fps)))
            if progress and progress(i + 1, total) is False:
                raise Cancelled()
        proc.stdin.close()
        err = proc.stderr.read().decode(errors='replace')
        if proc.wait() != 0:
            raise RuntimeError('FFmpeg could not write the video:\n' + err[-1500:])
    except BaseException:
        proc.kill()
        proc.wait()
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        raise
    return path
