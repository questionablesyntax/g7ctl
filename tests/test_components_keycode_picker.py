"""KeycodePicker tests, A2 of the redesign. Runs headless (offscreen
platform); skipped entirely if PyQt6 is absent.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - depends on the environment
    QApplication = None


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class KeycodePickerPopulationTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_default_item_is_first_with_none_data(self):
        from PyQt6.QtCore import Qt

        from g7ctlc.keycode_picker import KeycodePicker

        picker = KeycodePicker()
        first = picker.list.item(0)
        self.assertEqual(first.text(), "(Default)")
        self.assertIsNone(first.data(Qt.ItemDataRole.UserRole))

    def test_group_headers_are_present_and_not_selectable(self):
        from PyQt6.QtCore import Qt

        from g7ctlc.keycode_picker import KeycodePicker

        picker = KeycodePicker()
        headers = [
            picker.list.item(row)
            for row in range(picker.list.count())
            if picker.list.item(row).text().startswith("—")
        ]
        self.assertGreater(len(headers), 0)
        for header in headers:
            self.assertFalse(header.flags() & Qt.ItemFlag.ItemIsSelectable)

    def test_every_known_keycode_is_reachable(self):
        from PyQt6.QtCore import Qt

        from g7ctlc.keycode_picker import KeycodePicker
        from pyg7.buttons import KNOWN_KEYCODES

        picker = KeycodePicker()
        reachable = {
            picker.list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(picker.list.count())
        }
        missing = set(KNOWN_KEYCODES) - reachable
        self.assertEqual(missing, set())


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class KeycodePickerRawPreservationTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_unrecognised_value_gets_its_own_raw_entry(self):
        from PyQt6.QtWidgets import QPushButton

        from g7ctlc.keycode_picker import KeycodePicker

        anchor = QPushButton("Pick")
        picker = KeycodePicker()
        picker.open_for(anchor, "0x11", known=False)
        texts = [picker.list.item(row).text() for row in range(picker.list.count())]
        self.assertIn("Raw: 0x11", texts)

    def test_known_value_does_not_get_a_raw_entry(self):
        from PyQt6.QtWidgets import QPushButton

        from g7ctlc.keycode_picker import KeycodePicker

        anchor = QPushButton("Pick")
        picker = KeycodePicker()
        picker.open_for(anchor, "a", known=True)
        texts = [picker.list.item(row).text() for row in range(picker.list.count())]
        self.assertFalse(any(t.startswith("Raw:") for t in texts))

    def test_opening_with_none_selects_default(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QPushButton

        from g7ctlc.keycode_picker import KeycodePicker

        anchor = QPushButton("Pick")
        picker = KeycodePicker()
        picker.open_for(anchor, None, known=True)
        current = picker.list.currentItem()
        self.assertIsNone(current.data(Qt.ItemDataRole.UserRole))


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class KeycodePickerFilteringTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_filtering_hides_non_matching_items(self):
        from g7ctlc.keycode_picker import KeycodePicker

        picker = KeycodePicker()
        picker._apply_filter("f1")
        visible = [
            picker.list.item(row).text()
            for row in range(picker.list.count())
            if not picker.list.item(row).isHidden()
        ]
        self.assertTrue(all("f1" in text.lower() for text in visible if not text.startswith("—")))
        self.assertIn("Keyboard: F1", visible)

    def test_default_and_raw_entries_hide_once_filtering(self):
        from PyQt6.QtWidgets import QPushButton

        from g7ctlc.keycode_picker import KeycodePicker

        anchor = QPushButton("Pick")
        picker = KeycodePicker()
        picker.open_for(anchor, "0x11", known=False)
        picker._apply_filter("f1")
        self.assertTrue(picker.list.item(0).isHidden())  # "(Default)"
        self.assertTrue(picker.list.item(1).isHidden())  # "Raw: 0x11"

    def test_a_filter_matching_nothing_reports_the_empty_search_copy(self):
        from g7ctlc.keycode_picker import KeycodePicker

        picker = KeycodePicker()
        picker._apply_filter("f13")
        self.assertEqual(picker.no_match_text(), 'No key matches "f13".')

    def test_clearing_the_filter_clears_the_empty_search_copy(self):
        from g7ctlc.keycode_picker import KeycodePicker

        picker = KeycodePicker()
        picker._apply_filter("f13")
        picker._apply_filter("")
        self.assertIsNone(picker.no_match_text())

    def test_headers_with_no_visible_children_are_hidden(self):
        from g7ctlc.keycode_picker import KeycodePicker

        picker = KeycodePicker()
        picker._apply_filter("f1")  # only the Keyboard group has F-row matches
        headers = [
            picker.list.item(row)
            for row in range(picker.list.count())
            if picker.list.item(row).text().startswith("—")
        ]
        by_text = {h.text(): h.isHidden() for h in headers}
        self.assertFalse(by_text["— Keyboard —"])
        self.assertTrue(by_text["— Mouse —"])


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class KeycodePickerKeyboardTest(unittest.TestCase):
    app = None

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_enter_in_the_search_box_chooses_the_current_item_and_closes(self):
        from PyQt6.QtCore import QEvent, Qt
        from PyQt6.QtGui import QKeyEvent
        from PyQt6.QtWidgets import QPushButton

        from g7ctlc.keycode_picker import KeycodePicker

        anchor = QPushButton("Pick")
        picker = KeycodePicker()
        picker.open_for(anchor, None, known=True)
        picker.list.setCurrentRow(0)  # "(Default)"

        chosen = []
        picker.codeChosen.connect(chosen.append)
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        self.assertTrue(picker.eventFilter(picker.search, event))
        self.assertEqual(chosen, [None])

    def test_escape_closes_without_choosing(self):
        from PyQt6.QtCore import QEvent, Qt
        from PyQt6.QtGui import QKeyEvent

        from g7ctlc.keycode_picker import KeycodePicker

        picker = KeycodePicker()
        chosen = []
        picker.codeChosen.connect(chosen.append)
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        picker.keyPressEvent(event)
        self.assertEqual(chosen, [])

    def test_down_from_the_search_box_moves_past_the_header(self):
        from g7ctlc.keycode_picker import KeycodePicker

        picker = KeycodePicker()
        picker.list.setCurrentRow(0)  # "(Default)"
        picker._move_current(+1)
        # row 1 is the first group's header -- the move must land on a real,
        # selectable item instead of stopping on it.
        from PyQt6.QtCore import Qt

        current = picker.list.currentItem()
        self.assertNotEqual(current.data(Qt.ItemDataRole.UserRole), "__header__")


if __name__ == "__main__":
    unittest.main()
