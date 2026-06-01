# Agent Instructions

This project is a fresh start for a tabular-data animated word cloud.

## Product Intent

Build an animation library that accepts keyframe tables, not raw text. A user
should be able to say which words exist, how large they are at each keyframe,
and then render a smooth animated word cloud.

## High-Level Approach

Use `amueller/word_cloud` for what it is good at:

- static word-cloud packing,
- masks and contours,
- font metrics,
- colors,
- Pillow-based rendering,
- deterministic layout via `random_state`.

Add our own animation logic around it:

- parse wide and long tabular keyframe inputs,
- interpolate word values between keyframes,
- maintain word identity across frames,
- optionally step a physics simulation so words can push each other and fill
  space as their current sizes change,
- export frames, video, and browser-playable vector animations.

## Hybrid Rendering Model

The preferred first architecture is:

1. Compute each word's maximum value across all keyframes.
2. Generate a `word_cloud.WordCloud` layout from those maximum values.
3. Convert each `layout_` entry into an internal `WordBody`.
4. Give each `WordBody`:
   - text,
   - base layout position,
   - current physics position,
   - orientation,
   - color,
   - peak font size,
   - current value,
   - current collision bounds.
5. During animation, update current sizes from interpolated values, resize
   collision bodies, step physics, and render from the current positions.

## Physics Behavior

Prefer current-size collision bodies for the first dynamic implementation. That
matches WordSwarm's feel: large words push neighbors away, and shrinking words
release space that other words can occupy.

Expose max-size collision bodies later as a stability option.

The physics layer should be replaceable. Do not bury data parsing or rendering
inside physics-specific code.

## Implementation Guidance

- Keep the core data model independent of CSV, pandas, Pillow, and Box2D where
  practical.
- Make deterministic output the default.
- Prefer small modules with narrow responsibilities:
  - `data`: input normalization and validation,
  - `layout`: `word_cloud` layout extraction,
  - `physics`: body updates and stepping,
  - `render`: frame drawing,
  - `animation`: timeline orchestration and export.
- Do not add text parsing or NLP until the table-driven workflow is working.
- Do not copy large chunks from WordSwarm. Borrow the concept, then implement it
  in modern Python.
- Document tradeoffs when changing collision policy, interpolation behavior, or
  rendering assumptions.

## Suggested Dependencies

Start with:

- `wordcloud`
- `pillow`
- `numpy`
- `pandas`
- `imageio`

Add a physics dependency only when the fixed-position renderer is working.
