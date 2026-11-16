# Motion Studio

A Filmora-style app focused on three things: **Transitions, Effects and Stickers**.
Build animated stickers on a timeline and export them with a transparent background
(ProRes 4444 `.mov`) to drop onto a video editor's timeline.
Default video: **2560 × 1440 at 60 fps** (changeable per project).

## Layout (like Filmora)
- **Library (top left):** Transitions / Effects / Stickers tabs, categories, search, and
  cards that play when you hover them. Click **+** or drag a card onto the timeline.
- **Player (top centre):** preview over a checkerboard, colour or your own background
  picture (never exported), timecode, frame stepping, video size, frame snapshot.
- **Properties (top right):** Sticker (text, placement, timing), Transitions (In and Out,
  any of 8 directions, duration, easing, distance, bounces) and Effects (stack, on/off,
  sliders, reset, remove).
- **Timeline (bottom):** tracks, drag to move, drag edges to trim, split, undo/redo,
  hide/lock tracks, zoom.

## Library contents
- **Transitions:** Slide, Bounce, Slow bounce, Squash drop, Pop, Zoom, Fade, Blur, Spin,
  Flip, Wipe, plus your saved ones under Mine.
- **Effects:** Motion (Float, Hop, Pulse, Wiggle, Swing, Spin, Shake, Blink) and Look
  (Drop Shadow, Glow, Outline, Tint, Black & White, Blur), plus Mine.
- **Stickers:** Mine (import your own PNG, SVG, GIF), built-in shapes, arrows, signs, and
  text styles.

Run from source: `pip install -r requirements.txt` then `python run.py`.
Tests: `python -m pytest tests`.

## Smoothness
- Preview frames are cached once made; editing one sticker only redraws the frames
  where it appears. While you are not playing, frames ahead of the playhead are
  prepared automatically (teal line under the ruler, "Ready to play").
- Playback follows an exact clock at the project frame rate.
- Export renders on several CPU cores, and the output file is only replaced once
  it is complete.

## Updates
Help > Check for updates (also checked automatically at start, can be turned off).
The app downloads the newest build from GitHub, restarts, and keeps your projects,
saved effects and stickers (they live in AppData). A log is kept at
%LOCALAPPDATA%\MotionStudio\update.log.
