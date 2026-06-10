# Examples

This directory contains reproducible input fixtures and small rendered previews
used by the project README.

## Inputs

- `simple_keyframes.csv`: five-word fixture with explicit word colors and
  simple growth/shrink patterns.
- `color_modes_keyframes.csv`: six-word fixture without explicit word colors,
  used to show `single`, `group`, and `word` color modes clearly.
- `bioit_top_terms_2016_2026.csv`: larger BioIT phrase-frequency fixture.
- `bioit_svg_config.toml`: TOML render configuration for the BioIT fixture.
- `palette_bioit.hex`: one-color-per-line palette used by the BioIT example.
- `scene_keyframes.csv`, `scene_config.toml`,
  `scene_settled_line_config.toml`, and `scene_attractors_config.toml`: compact
  scene-mode fixtures with uneven scene spans, a recurring word, the
  `opabinia.png` image item, settled-line positioning, and named attractor
  clusters.
- `opabinia.png`: static PNG asset used by the scene-mode fixture to demonstrate
  `type=image`, responsive `asset_scale`, and `layer` ordering.

## Rendered Previews

Preview GIFs live in `renders/` and are intentionally small enough to commit.
Regenerate them with:

```bash
python3 scripts/render_examples.py
```

The generated previews cover fixed versus physics positioning, color modes,
linear versus smoothstep interpolation, and a 9:16 vertical social format.
