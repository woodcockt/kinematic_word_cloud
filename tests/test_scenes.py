from __future__ import annotations

import pandas as pd
import pytest

import kinematic_word_cloud.scenes as scene_module
from kinematic_word_cloud.api import RenderOptions, render_animation
from kinematic_word_cloud.data import KeyframeDataError
from kinematic_word_cloud.scenes import (
    SCENE_LAYOUT_MODE,
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
