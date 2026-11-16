# Motion Studio

A small Windows app for making animated objects with full control, exported with a
transparent background to drop onto a video editor's timeline (made for Filmora).

- **Objects:** pictures (PNG, JPG, WebP), SVG, animated GIF/WebP, or text.
- **In / Loop / Out effects:** Fade, Slide, Bounce, Slow bounce, Pop, Zoom, Spin, Flip,
  Wipe, Blur, Squash drop; loops Float, Hop, Pulse, Wiggle, Swing, Spin, Shake, Blink.
- **Any direction** for moving effects (8 ways), plus easing, distance, strength,
  bounce count and timing.
- **My effects:** save your own settings and reuse them.
- **Export:** ProRes 4444 `.mov` with transparency (default), or a PNG sequence.
- Preview over a checkerboard, a solid colour, or your own background picture
  (preview only, never exported).

Run from source: `pip install -r requirements.txt` then `python run.py`.
Tests: `python -m pytest tests`.
