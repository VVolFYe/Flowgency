"""Gate-mode scene config, polygon geometry, and the draw-gates editor state machine (pure)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from backend.vision.draw_gates import GateEditor, default_scene
from backend.vision.geometry import (
    convex_hull,
    is_convex,
    is_simple,
    point_in_polygon,
    polygon_area,
    polygon_width,
    polygons_overlap,
)
from backend.vision.scene import GATE_IDS, SceneConfig, SceneError, load_scene, save_scene


def rect(x1: float, y1: float, x2: float, y2: float):
    return ((x1, y1), (x2, y1), (x2, y2), (x1, y2))


# A plausible 400x400 crossroads: arms named by image side, right-hand traffic.
GATES = {
    "north_in.far": rect(150, 0, 195, 40), "north_in.stop": rect(150, 120, 195, 155), "north_out": rect(205, 80, 250, 115),
    "east_in.far": rect(360, 150, 400, 195), "east_in.stop": rect(245, 150, 280, 195), "east_out": rect(285, 205, 320, 250),
    "south_in.far": rect(205, 360, 250, 400), "south_in.stop": rect(205, 245, 250, 280), "south_out": rect(150, 285, 195, 320),
    "west_in.far": rect(0, 205, 40, 250), "west_in.stop": rect(120, 205, 155, 250), "west_out": rect(80, 150, 115, 195),
}


def scene(**overrides) -> SceneConfig:
    data = default_scene("test_scene", "youtube/clip.mp4", (400, 400)).model_dump()
    data["gates"] = GATES
    data.update(overrides)
    return SceneConfig.model_validate(data)


class GeometryTests(unittest.TestCase):
    def test_point_in_polygon_including_boundary(self) -> None:
        square = rect(0, 0, 10, 10)
        self.assertTrue(point_in_polygon((5, 5), square))
        self.assertTrue(point_in_polygon((10, 5), square))
        self.assertTrue(point_in_polygon((0, 0), square))
        self.assertFalse(point_in_polygon((10.1, 5), square))
        concave = ((0, 0), (10, 0), (5, 3), (10, 10), (0, 10))
        self.assertFalse(point_in_polygon((8, 3), concave))
        self.assertTrue(point_in_polygon((2, 3), concave))

    def test_simple_convex_area_width(self) -> None:
        self.assertTrue(is_simple(rect(0, 0, 10, 4)))
        self.assertFalse(is_simple(((0, 0), (10, 4), (10, 0), (0, 4))))  # bow tie
        self.assertFalse(is_simple(((0, 0), (0, 0), (10, 4), (0, 4))))
        self.assertTrue(is_convex(rect(0, 0, 10, 4)))
        self.assertFalse(is_convex(((0, 0), (10, 0), (2, 2), (0, 10))))
        self.assertEqual(polygon_area(rect(0, 0, 10, 4)), 40)
        self.assertAlmostEqual(polygon_width(rect(0, 0, 100, 30)), 30)
        slanted = ((0, 0), (100, 100), (100, 142.43), (0, 42.43))  # 30 px deep band at 45 degrees
        self.assertAlmostEqual(polygon_width(slanted), 30, places=1)

    def test_overlap_and_hull(self) -> None:
        self.assertTrue(polygons_overlap(rect(0, 0, 10, 10), rect(5, 5, 15, 15)))
        self.assertTrue(polygons_overlap(rect(0, 0, 10, 10), rect(2, 2, 4, 4)))  # contained
        self.assertTrue(polygons_overlap(rect(0, 0, 10, 10), rect(10, 0, 20, 10)))  # shared edge
        self.assertFalse(polygons_overlap(rect(0, 0, 10, 10), rect(11, 0, 20, 10)))
        hull = convex_hull([*rect(0, 0, 10, 2), *rect(0, 20, 10, 22), (5, 10)])
        self.assertEqual(sorted(hull), sorted([(0, 0), (10, 0), (10, 22), (0, 22)]))


class SceneTests(unittest.TestCase):
    def test_valid_scene_has_no_warnings_and_derives_regions(self) -> None:
        s = scene()
        self.assertEqual(list(s.gates), list(GATE_IDS))
        self.assertEqual(s.warnings(), [])
        self.assertEqual(sorted(s.approach_region("north")), sorted(rect(150, 0, 195, 155)))
        self.assertEqual(s.locate((170, 80)), "north")
        self.assertEqual(s.locate((200, 200)), "junction")
        self.assertEqual(s.locate((300, 300)), None)  # building corner outside the hull
        self.assertEqual(s.locate((170, 140)), "north")  # inside the stop gate = still on the approach

    def test_missing_gates_make_regions_unknown(self) -> None:
        gates = dict(GATES)
        del gates["east_out"], gates["west_in.far"]
        s = scene(gates=gates)
        self.assertIsNone(s.approach_region("west"))
        self.assertIsNone(s.junction_region())
        self.assertIn("missing gates: east_out, west_in.far", s.warnings())

    def test_invalid_ids_and_polygons_rejected(self) -> None:
        for gates in ({"north_in": rect(0, 0, 50, 50)},
                      {"northbound_in.stop": rect(0, 0, 50, 50)},
                      {"north_in.stop": ((0, 0), (50, 50), (50, 0), (0, 50))},       # bow tie
                      {"north_in.stop": ((0, 0), (50, 0), (50, 50))},                # 3 points
                      {"north_in.stop": rect(0, 0, 5, 5)},                           # tiny
                      {"north_in.stop": rect(390, 0, 410, 50)}):                     # outside frame
            with self.assertRaises(ValidationError, msg=str(gates)):
                scene(gates=gates)
        with self.assertRaises(ValidationError):
            scene(model_id="yolo11s.pt")

    def test_overlap_thin_and_region_warnings(self) -> None:
        gates = dict(GATES)
        gates["north_out"] = rect(180, 100, 250, 130)  # overlaps north_in.stop
        gates["west_out"] = rect(80, 150, 100, 195)    # 20 px deep
        warnings = scene(gates=gates).warnings()
        self.assertIn("gates overlap: north_in.stop and north_out", warnings)
        self.assertTrue(any(w.startswith("west_out: only 20 px deep") for w in warnings))
        gates = dict(GATES)
        gates["west_out"] = rect(160, 60, 190, 100)  # inside the north approach hull
        self.assertIn("approach region north (hull of its far+stop gates) reaches gate west_out",
                      scene(gates=gates).warnings())

    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            save_scene(scene(), path)
            text = path.read_text(encoding="utf-8")
            self.assertIn('"north_in.far": [[150.0, 0.0], [195.0, 0.0]', text)
            self.assertEqual(load_scene(path), scene())
            path.write_text(json.dumps({"scene_id": "x"}), encoding="utf-8")
            with self.assertRaises(SceneError):
                load_scene(path)
        with self.assertRaises(SceneError):
            load_scene(Path("/nonexistent/scene.json"))


class EditorTests(unittest.TestCase):
    def test_four_clicks_store_gate_and_advance(self) -> None:
        editor = GateEditor((400, 400))
        self.assertEqual(editor.selected, "north_in.far")
        for x, y in rect(150, 0, 195, 40):
            editor.click(x, y)
        self.assertEqual(editor.gates["north_in.far"], rect(150, 0, 195, 40))
        self.assertEqual(editor.selected, "north_in.stop")
        self.assertTrue(editor.dirty)

    def test_invalid_polygon_rejected_and_points_cleared(self) -> None:
        editor = GateEditor((400, 400))
        for x, y in ((0, 0), (50, 50), (50, 0), (0, 50)):
            editor.click(x, y)
        self.assertNotIn("north_in.far", editor.gates)
        self.assertEqual(editor.points, [])
        self.assertTrue(editor.message.startswith("Rejected"))

    def test_select_redo_undo_delete(self) -> None:
        editor = GateEditor((400, 400), dict(GATES))
        self.assertEqual(editor.selected, "north_in.far")  # nothing missing: first gate
        editor.select("west_out")
        editor.redo()
        self.assertNotIn("west_out", editor.gates)
        editor.click(80, 150)
        editor.click(115, 150)
        editor.undo_point()
        self.assertEqual(editor.points, [(80, 150)])
        self.assertTrue(editor.cancel_points())
        editor.select("east_out")
        editor.delete()
        self.assertEqual(editor.missing(), ["east_out", "west_out"])
        editor.select("bogus")
        self.assertEqual(editor.selected, "east_out")

    def test_resume_selects_first_missing_and_builds_scene(self) -> None:
        gates = {k: v for k, v in GATES.items() if k != "south_in.stop"}
        editor = GateEditor((400, 400), gates)
        self.assertEqual(editor.selected, "south_in.stop")
        for x, y in GATES["south_in.stop"]:
            editor.click(x, y)
        built = editor.build_scene(scene(gates={}), reference_frame_index=12)
        self.assertEqual(built, scene(reference_frame_index=12))

    def test_clicks_clamped_to_frame(self) -> None:
        editor = GateEditor((400, 400))
        editor.click(-5, 410)
        self.assertEqual(editor.points, [(0.0, 400.0)])


if __name__ == "__main__":
    unittest.main()
