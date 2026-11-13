"""draw-lines editor state machine (pure; no window)."""

from __future__ import annotations

import unittest

from backend.vision.draw_lines import ApproachEditor, Mode, inbound_arrow

ENTER, ESC, BACKSPACE = 13, 27, 8


def type_text(editor: ApproachEditor, text: str) -> None:
    for ch in text:
        editor.key(ord(ch))


class EditorTests(unittest.TestCase):
    def test_add_approach_full_flow(self) -> None:
        editor = ApproachEditor((352, 288))
        editor.start_approach()
        type_text(editor, "Southbound_inx")
        editor.key(BACKSPACE)
        editor.key(ENTER)
        self.assertIs(editor.mode, Mode.POINTS)
        editor.click(50, 100)
        editor.click(150, 100)
        editor.click(100, 130)
        self.assertIs(editor.mode, Mode.CONFIRM)
        editor.key(ENTER)
        self.assertIs(editor.mode, Mode.BROWSE)
        self.assertTrue(editor.dirty)
        camera = editor.build_camera("J1", "cam", "ref.jpg")
        approach = camera.approaches[0]
        self.assertEqual(approach.approach_id, "southbound_in")
        self.assertEqual(approach.line, ((50.0, 100.0), (150.0, 100.0)))
        self.assertIsNone(approach.sumo_edge_id)

    def test_invalid_id_stays_in_typing(self) -> None:
        editor = ApproachEditor((352, 288))
        editor.start_approach()
        type_text(editor, "south_in")
        editor.key(ENTER)
        self.assertIs(editor.mode, Mode.TYPING)
        self.assertIn("compass", editor.message)

    def test_duplicate_rejected_and_delete_last(self) -> None:
        editor = ApproachEditor((352, 288))
        for _ in range(2):
            editor.start_approach()
            type_text(editor, "westbound_in")
            editor.key(ENTER)
        self.assertIs(editor.mode, Mode.POINTS)  # first time fine
        editor.click(10, 10), editor.click(10, 100), editor.click(0, 50)
        editor.key(ENTER)
        editor.start_approach()
        type_text(editor, "westbound_in")
        editor.key(ENTER)
        self.assertIs(editor.mode, Mode.TYPING)
        editor.key(ESC)
        editor.delete_last()
        self.assertEqual(editor.approaches, [])

    def test_collinear_inbound_point_restarts_clicks(self) -> None:
        editor = ApproachEditor((352, 288))
        editor.start_approach()
        type_text(editor, "northbound_in")
        editor.key(ENTER)
        editor.click(10, 10), editor.click(100, 10), editor.click(50, 10)
        self.assertIs(editor.mode, Mode.POINTS)
        self.assertEqual(editor.points, [])

    def test_clicks_clamped_to_frame(self) -> None:
        editor = ApproachEditor((352, 288))
        editor.start_approach()
        type_text(editor, "eastbound_in")
        editor.key(ENTER)
        editor.click(-5, 400)
        self.assertEqual(editor.points[0], (0.0, 288.0))

    def test_arrow_points_to_inbound_side(self) -> None:
        start, end = inbound_arrow(((0, 0), (100, 0)), (50, -30))
        self.assertEqual(start, (50, 0))
        self.assertLess(end[1], 0)
        start, end = inbound_arrow(((0, 0), (100, 0)), (50, 30))
        self.assertGreater(end[1], 0)


if __name__ == "__main__":
    unittest.main()
