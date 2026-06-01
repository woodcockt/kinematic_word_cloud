# Kinematic Word Cloud

Kinematic Word Cloud is an early-stage experiment for animating word clouds from
tabular keyframe data.

The project goal is to combine two useful ideas:

- Use [`word_cloud`](https://github.com/amueller/word_cloud) for high-quality
  word placement, masks, font sizing, colors, and rendering.
- Add a lightweight physics/tweening layer so words can grow, shrink, drift, and
  make room for each other across keyframes.

This is intentionally not a text-mining project. The primary input should be a
table of words and values over time.

## Target Input

The first supported format should be a wide keyframe table:

```csv
word,color,group,2024-01,2024-02,2024-03
python,#3776AB,language,10,25,5
visualization,,design,4,18,22
animation,,motion,0,8,30
```

See [examples/simple_keyframes.csv](examples/simple_keyframes.csv) for a tiny
fixture with five words and three keyframes. It includes one word shrinking from
large to small, one growing to its maximum in the final frame, and one peaking
in the middle frame.

The `color` and `group` columns are optional metadata:

- `color`: explicit word color as `#RGB` or `#RRGGBB`.
- `group`: words in the same group receive the same deterministic color unless
  the word has an explicit `color`.
- words without either receive a deterministic fallback palette color.

A long format can be supported as a convenience:

```csv
frame,word,value
2024-01,python,10
2024-02,python,25
2024-01,visualization,4
```

## Proposed Architecture

1. Normalize the keyframe table into a matrix of `word x frame -> value`.
2. Compute each word's peak value across all frames.
3. Generate an initial packed layout with `word_cloud.WordCloud` from those peak
   values.
4. Create one physics body per word at its layout position.
5. Anchor each body near its original layout position with a spring-like force.
6. For every rendered frame:
   - interpolate values between adjacent keyframes,
   - resize each word's collision body to the current value,
   - step the physics world,
   - draw words at the current physics positions using Pillow or `word_cloud`
     layout data,
   - write the frame to an image or video encoder.

## Design Decisions

- Generate initial layout from peak values so the first layout is collision-aware
  for the largest expected word sizes.
- Use current-size collision bodies when we want words to fill newly freed space.
- Use max-size collision bodies when we want stable reserved space.
- Keep the animation deterministic by default with explicit random seeds.
- Treat text parsing as out of scope for the core library.

## Early Milestones

1. Load and validate wide CSV keyframe data.
2. Generate a static peak-value word cloud from the table.
3. Render interpolated frames with fixed positions.
4. Add physics-driven current-size collision bodies.
5. Export GIF, MP4, or SVG output.

## Status

This repository is newly scaffolded. The first prototype can load a wide
keyframe CSV, render static and interpolated PNG frames, optionally use the
lightweight physics solver, and export GIF, MP4, or sampled animated SVG.

## Current Prototype

Render the first static peak-value cloud from the example data:

```bash
python3 scripts/create_starting_cloud.py
```

The script writes `output/starting_cloud.png`.

Render fixed-position interpolated PNG frames:

```bash
python3 scripts/create_fixed_frames.py
```

The script writes a PNG sequence to `output/fixed_frames/`.

Render the same sequence with the lightweight physics solver enabled:

```bash
python3 scripts/create_fixed_frames.py --physics
```

The physics path writes to `output/physics_frames/`.

Physics mode uses the first keyframe's word-cloud layout as the anchor layout,
then lets later growth/shrinkage push words around with current-size collision
bodies.

Export GIF and MP4 outputs:

```bash
python3 scripts/create_fixed_frames.py --gif --mp4
python3 scripts/create_fixed_frames.py --physics --gif --mp4
```

GIF export uses Pillow. MP4 export uses the local `ffmpeg` binary.
The default playback rate is 12 fps. Use `--fps` for playback rate and
`--frames-per-transition` for interpolation density:

```bash
python3 scripts/create_fixed_frames.py --gif --fps 12 --frames-per-transition 24
```

You can also set total duration or per-transition duration. In duration mode,
`--fps` becomes the target frame rate, still defaulting to 12 fps, and the
script calculates the rendered frames per transition:

```bash
python3 scripts/create_fixed_frames.py --gif --total-duration 6 --fps 24
python3 scripts/create_fixed_frames.py --mp4 --seconds-per-transition 2 --fps 24
```

The script nudges the effective FPS when needed so the animation lands exactly
on each keyframe and still matches the requested duration.

Export sampled animated SVG:

```bash
python3 scripts/create_fixed_frames.py --svg
python3 scripts/create_fixed_frames.py --physics --svg
```

SVG export writes browser-playable SMIL animation to `output/fixed_animation.svg`
or `output/physics_animation.svg`. It samples the same timeline as the PNG
renderer and animates each word's translation, font size, and opacity. Because
the SVG uses browser text rendering, exact glyph bounds may differ slightly from
the Pillow-rendered PNG/MP4/GIF outputs.
