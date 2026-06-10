from __future__ import annotations

import pandas as pd
import pytest
from PIL import Image

import kinematic_word_cloud.scenes as scene_module
from kinematic_word_cloud.api import RenderOptions, render_animation
from kinematic_word_cloud.data import KeyframeDataError
from kinematic_word_cloud.render_config import resolve_scene_attractors
from kinematic_word_cloud.scenes import (
    ATTRACTORS_SCENE_POSITIONING,
    SCENE_LAYOUT_MODE,
    SETTLED_CENTER_SCENE_POSITIONING,
    SETTLED_LINE_SCENE_POSITIONING,
    _line_anchor_points,
    from_scene_dataframe,
    render_scene_animation_frames,
)


SCENE_STARTS = {
    "intro": "s001",
    "chorus": "s004",
    "outro": "s006",
}


def scene_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "scene": "intro",
                "id": "python",
                "word": "python",
                "color": "#3776AB",
                "group": "tech",
                "x": 0.35,
                "y": 0.50,
                "s001": 0,
                "s002": 0.7,
                "s003": 1.0,
                "s004": 0,
                "s005": 0,
                "s006": 0,
                "s007": 0,
            },
            {
                "scene": "intro",
                "id": "layout",
                "word": "layout",
                "color": "#E76F51",
                "group": "design",
                "x": "",
                "y": "",
                "s001": 0,
                "s002": 0.3,
                "s003": 0.9,
                "s004": 0,
                "s005": 0,
                "s006": 0,
                "s007": 0,
            },
            {
                "scene": "chorus",
                "id": "python",
                "word": "python",
                "color": "#3776AB",
                "group": "tech",
                "x": "",
                "y": "",
                "s001": 0,
                "s002": 0,
                "s003": 0,
                "s004": 0.8,
                "s005": 1.0,
                "s006": 0,
                "s007": 0,
            },
            {
                "scene": "chorus",
                "id": "motion",
                "word": "motion",
                "color": "#2A9D8F",
                "group": "design",
                "x": 0.70,
                "y": 0.45,
                "s001": 0,
                "s002": 0,
                "s003": 0,
                "s004": 0.2,
                "s005": 0.9,
                "s006": 0,
                "s007": 0,
            },
            {
                "scene": "outro",
                "id": "python",
                "word": "python",
                "color": "#3776AB",
                "group": "tech",
                "x": 0.80,
                "y": 0.55,
                "s001": 0,
                "s002": 0,
                "s003": 0,
                "s004": 0,
                "s005": 0,
                "s006": 0.6,
                "s007": 0.1,
            },
            {
                "scene": "outro",
                "id": "fade",
                "word": "fade",
                "color": "#E9C46A",
                "group": "design",
                "x": "",
                "y": "",
                "s001": 0,
                "s002": 0,
                "s003": 0,
                "s004": 0,
                "s005": 0,
                "s006": 0.8,
                "s007": 0,
            },
        ]
    )


def scene_dataframe_with_attractors() -> pd.DataFrame:
    dataframe = scene_dataframe()
    dataframe["attractor"] = [
        "left",
        "right",
        "right",
        "left",
        "left",
        "right",
    ]
    return dataframe


def test_scene_parser_defaults_id_and_allows_recurring_ids() -> None:
    dataframe = scene_dataframe().drop(columns=["id"])

    scene_data = from_scene_dataframe(dataframe, scene_starts=SCENE_STARTS)

    assert [scene.name for scene in scene_data.scenes] == [
        "intro",
        "chorus",
        "outro",
    ]
    assert scene_data.scenes[0].ids_by_word["python"] == "python"
    assert scene_data.scenes[1].ids_by_word["python"] == "python"
    assert scene_data.scenes[0].frames == ["s001", "s002", "s003"]
    assert scene_data.scenes[1].frames == ["s004", "s005"]
    assert scene_data.scenes[2].frames == ["s006", "s007"]


def test_scene_parser_reads_optional_attractor_column() -> None:
    scene_data = from_scene_dataframe(
        scene_dataframe_with_attractors(),
        scene_starts=SCENE_STARTS,
    )

    assert scene_data.scenes[0].attractors_by_word == {
        "python": "left",
        "layout": "right",
    }
    assert scene_data.scenes[1].attractors_by_word["python"] == "right"


def test_scene_parser_rejects_unknown_start_label() -> None:
    with pytest.raises(KeyframeDataError, match="unknown frame label"):
        from_scene_dataframe(
            scene_dataframe(),
            scene_starts={"intro": "s001", "chorus": "missing"},
        )


def test_scene_parser_rejects_unknown_csv_scene() -> None:
    dataframe = scene_dataframe()
    dataframe.loc[0, "scene"] = "bridge"

    with pytest.raises(KeyframeDataError, match="Unknown scenes: bridge"):
        from_scene_dataframe(dataframe, scene_starts=SCENE_STARTS)


def test_scene_parser_rejects_duplicate_visible_words_in_one_scene() -> None:
    dataframe = scene_dataframe()
    dataframe.loc[1, "word"] = "python"
    dataframe.loc[1, "id"] = "python_two"

    with pytest.raises(KeyframeDataError, match="Duplicate word"):
        from_scene_dataframe(dataframe, scene_starts=SCENE_STARTS)


def test_scene_parser_rejects_duplicate_ids_in_one_scene() -> None:
    dataframe = scene_dataframe()
    dataframe.loc[1, "id"] = "python"

    with pytest.raises(KeyframeDataError, match="Duplicate id"):
        from_scene_dataframe(dataframe, scene_starts=SCENE_STARTS)


def test_scene_render_writes_continuous_frames_and_carries_positions(tmp_path) -> None:
    scene_data = from_scene_dataframe(scene_dataframe(), scene_starts=SCENE_STARTS)

    frame_paths, scene_info = render_scene_animation_frames(
        scene_data,
        tmp_path,
        frames_per_transition=1,
        width=320,
        height=180,
        random_state=3,
    )

    assert [path.name for path in frame_paths] == [
        f"frame_{index:04d}.png" for index in range(7)
    ]
    assert [info.frame_count for info in scene_info] == [3, 2, 2]
    intro_python = scene_info[0].centers_by_id["python"]
    chorus_python = scene_info[1].centers_by_id["python"]
    outro_python = scene_info[2].centers_by_id["python"]
    assert chorus_python == pytest.approx(intro_python)
    assert outro_python == pytest.approx((256.0, 99.0))


def test_scene_render_keeps_visible_boundary_word_center(tmp_path, monkeypatch) -> None:
    scene_data = from_scene_dataframe(scene_dataframe(), scene_starts=SCENE_STARTS)
    original_render_fixed_frame = scene_module.render_fixed_frame
    rendered_frames = []

    def spy_render_fixed_frame(table, layout, values, output_path, **kwargs):
        rendered_frames.append(
            {
                "values": dict(values),
                "centers": dict(kwargs["centers"]),
            }
        )
        return original_render_fixed_frame(table, layout, values, output_path, **kwargs)

    monkeypatch.setattr(scene_module, "render_fixed_frame", spy_render_fixed_frame)

    render_scene_animation_frames(
        scene_data,
        tmp_path,
        frames_per_transition=1,
        width=320,
        height=180,
        random_state=3,
    )

    intro_final = rendered_frames[2]
    chorus_first = rendered_frames[3]
    assert intro_final["values"]["python"] > 0
    assert chorus_first["values"]["python"] > 0
    assert chorus_first["centers"]["python"] == pytest.approx(
        intro_final["centers"]["python"]
    )


def test_scene_settled_center_locks_carryover_during_warmup(
    tmp_path,
    monkeypatch,
) -> None:
    scene_data = from_scene_dataframe(scene_dataframe(), scene_starts=SCENE_STARTS)
    original_render_fixed_frame = scene_module.render_fixed_frame
    rendered_frames = []

    def spy_render_fixed_frame(table, layout, values, output_path, **kwargs):
        rendered_frames.append(
            {
                "values": dict(values),
                "centers": dict(kwargs["centers"]),
            }
        )
        return original_render_fixed_frame(table, layout, values, output_path, **kwargs)

    monkeypatch.setattr(scene_module, "render_fixed_frame", spy_render_fixed_frame)

    render_scene_animation_frames(
        scene_data,
        tmp_path,
        frames_per_transition=1,
        width=320,
        height=180,
        random_state=3,
        scene_positioning=SETTLED_CENTER_SCENE_POSITIONING,
        scene_settle_steps=40,
    )

    intro_final = rendered_frames[2]
    chorus_first = rendered_frames[3]
    assert intro_final["values"]["python"] > 0
    assert chorus_first["values"]["python"] > 0
    assert chorus_first["centers"]["python"] == pytest.approx(
        intro_final["centers"]["python"]
    )


def test_settled_line_anchor_points_follow_medial_axis() -> None:
    assert _line_anchor_points(3, width=1280, height=720) == pytest.approx(
        [
            (500.0, 360.0),
            (640.0, 360.0),
            (780.0, 360.0),
        ]
    )
    assert _line_anchor_points(3, width=720, height=1280) == pytest.approx(
        [
            (360.0, 500.0),
            (360.0, 640.0),
            (360.0, 780.0),
        ]
    )
    assert _line_anchor_points(2, width=720, height=720) == pytest.approx(
        [
            (360.0, 360.0),
            (360.0, 360.0),
        ]
    )


def test_scene_settled_line_renders_continuous_frames(tmp_path) -> None:
    scene_data = from_scene_dataframe(scene_dataframe(), scene_starts=SCENE_STARTS)

    frame_paths, scene_info = render_scene_animation_frames(
        scene_data,
        tmp_path,
        frames_per_transition=1,
        width=320,
        height=180,
        random_state=3,
        scene_positioning=SETTLED_LINE_SCENE_POSITIONING,
        scene_settle_steps=20,
    )

    assert [path.name for path in frame_paths] == [
        f"frame_{index:04d}.png" for index in range(7)
    ]
    assert [info.frame_count for info in scene_info] == [3, 2, 2]


def test_attractor_scene_positioning_uses_named_anchor_points() -> None:
    scene_data = from_scene_dataframe(
        scene_dataframe_with_attractors(),
        scene_starts=SCENE_STARTS,
    )

    text_anchors, image_anchors = scene_module._settled_scene_anchor_centers(
        scene_data.scenes[0],
        scene_positioning=ATTRACTORS_SCENE_POSITIONING,
        scene_attractors={
            "left": (0.25, 0.50),
            "right": (0.75, 0.50),
        },
        width=200,
        height=100,
    )

    assert text_anchors["python"] == pytest.approx((50, 50))
    assert text_anchors["layout"] == pytest.approx((150, 50))
    assert image_anchors == {}


def test_scene_attractor_render_writes_continuous_frames(tmp_path) -> None:
    scene_data = from_scene_dataframe(
        scene_dataframe_with_attractors(),
        scene_starts=SCENE_STARTS,
    )

    frame_paths, scene_info = render_scene_animation_frames(
        scene_data,
        tmp_path,
        frames_per_transition=1,
        width=320,
        height=180,
        random_state=3,
        scene_positioning=ATTRACTORS_SCENE_POSITIONING,
        scene_attractors={
            "left": (0.30, 0.50),
            "right": (0.70, 0.50),
        },
        scene_settle_steps=20,
    )

    assert [path.name for path in frame_paths] == [
        f"frame_{index:04d}.png" for index in range(7)
    ]
    assert [info.frame_count for info in scene_info] == [3, 2, 2]


def test_scene_attractor_render_rejects_unknown_attractor(tmp_path) -> None:
    scene_data = from_scene_dataframe(
        scene_dataframe_with_attractors(),
        scene_starts=SCENE_STARTS,
    )

    with pytest.raises(KeyframeDataError, match="unknown attractor"):
        render_scene_animation_frames(
            scene_data,
            tmp_path,
            frames_per_transition=1,
            width=320,
            height=180,
            random_state=3,
            scene_positioning=ATTRACTORS_SCENE_POSITIONING,
            scene_attractors={"left": (0.30, 0.50)},
        )


def test_resolve_scene_attractors_from_config() -> None:
    resolved = resolve_scene_attractors(
        object(),
        {"attractors": {"left": {"x": 0.25, "y": 0.50}}},
    )

    assert resolved == {"left": (0.25, 0.50)}


def test_resolve_scene_attractors_rejects_invalid_coordinates() -> None:
    with pytest.raises(KeyframeDataError, match="between 0 and 1"):
        resolve_scene_attractors(
            object(),
            {"attractors": {"left": {"x": 1.25, "y": 0.50}}},
        )


def test_scene_render_composites_png_image_item(tmp_path) -> None:
    asset_path = tmp_path / "sprite.png"
    tall_asset_path = tmp_path / "tall.png"
    Image.new("RGBA", (10, 5), (255, 0, 0, 255)).save(asset_path)
    Image.new("RGBA", (10, 40), (0, 0, 255, 255)).save(tall_asset_path)
    dataframe = pd.DataFrame(
        [
            {
                "scene": "intro",
                "id": "anchor",
                "word": "anchor",
                "type": "text",
                "asset": "",
                "asset_scale": "",
                "layer": "",
                "attractor": "",
                "x": 0.10,
                "y": 0.10,
                "s001": 0.5,
                "s002": 0.5,
            },
            {
                "scene": "intro",
                "id": "sprite",
                "word": "",
                "type": "image",
                "asset": "sprite.png",
                "asset_scale": 0.25,
                "layer": "front",
                "attractor": "logo",
                "x": 0.50,
                "y": 0.50,
                "s001": 0,
                "s002": 1,
            },
            {
                "scene": "intro",
                "id": "tall",
                "word": "",
                "type": "image",
                "asset": "tall.png",
                "asset_scale": 0.25,
                "layer": "back",
                "attractor": "poster",
                "x": 0.80,
                "y": 0.50,
                "s001": 0,
                "s002": 1,
            },
        ]
    )
    scene_data = from_scene_dataframe(
        dataframe,
        scene_starts={"intro": "s001"},
        source=tmp_path / "scene.csv",
    )

    frame_paths, scene_info = render_scene_animation_frames(
        scene_data,
        tmp_path / "frames",
        frames_per_transition=1,
        width=120,
        height=80,
        random_state=3,
    )

    assert scene_data.scenes[0].image_items[0].asset_path == asset_path
    assert scene_data.scenes[0].image_items[0].layer == "front"
    assert scene_data.scenes[0].image_items[0].attractor == "logo"
    assert scene_data.scenes[0].image_items[1].layer == "back"
    assert scene_data.scenes[0].image_items[1].attractor == "poster"
    assert scene_info[0].centers_by_id["sprite"] == pytest.approx((60, 40))
    assert scene_info[0].peak_sizes_by_id["sprite"] == (30, 15)
    assert scene_info[0].peak_sizes_by_id["tall"] == (5, 20)
    final_frame = Image.open(frame_paths[-1]).convert("RGBA")
    assert final_frame.getpixel((60, 40))[:3] == (255, 0, 0)


def test_scene_parser_rejects_image_without_explicit_id(tmp_path) -> None:
    asset_path = tmp_path / "sprite.png"
    Image.new("RGBA", (10, 10), (255, 0, 0, 255)).save(asset_path)
    dataframe = pd.DataFrame(
        [
            {
                "scene": "intro",
                "id": "anchor",
                "word": "anchor",
                "type": "text",
                "asset": "",
                "s001": 1,
                "s002": 1,
            },
            {
                "scene": "intro",
                "id": "",
                "word": "",
                "type": "image",
                "asset": "sprite.png",
                "x": 0.50,
                "y": 0.50,
                "s001": 0,
                "s002": 1,
            },
        ]
    )

    with pytest.raises(KeyframeDataError, match="explicit id"):
        from_scene_dataframe(
            dataframe,
            scene_starts={"intro": "s001"},
            source=tmp_path / "scene.csv",
        )


def test_scene_parser_rejects_invalid_image_layer(tmp_path) -> None:
    asset_path = tmp_path / "sprite.png"
    Image.new("RGBA", (10, 10), (255, 0, 0, 255)).save(asset_path)
    dataframe = pd.DataFrame(
        [
            {
                "scene": "intro",
                "id": "anchor",
                "word": "anchor",
                "type": "text",
                "asset": "",
                "layer": "",
                "s001": 1,
                "s002": 1,
            },
            {
                "scene": "intro",
                "id": "sprite",
                "word": "",
                "type": "image",
                "asset": "sprite.png",
                "layer": "middle",
                "x": 0.50,
                "y": 0.50,
                "s001": 0,
                "s002": 1,
            },
        ]
    )

    with pytest.raises(KeyframeDataError, match="Image layer"):
        from_scene_dataframe(
            dataframe,
            scene_starts={"intro": "s001"},
            source=tmp_path / "scene.csv",
        )


def test_scene_mode_rejects_svg_export(tmp_path) -> None:
    csv_path = tmp_path / "scene.csv"
    scene_dataframe().to_csv(csv_path, index=False)

    with pytest.raises(KeyframeDataError, match="does not support SVG"):
        render_animation(
            RenderOptions(
                input_path=csv_path,
                output_dir=tmp_path / "frames",
                exports=("svg",),
                layout_mode=SCENE_LAYOUT_MODE,
                scene_starts=SCENE_STARTS,
            )
        )
