import unittest
from types import SimpleNamespace
from unittest.mock import patch

from widget import Widget


class ClickTest(unittest.TestCase):
    def test_codex_click_opens_chatgpt_without_detaching(self):
        widget = Widget.__new__(Widget)
        widget.drag = (10, 10)
        widget.drag_start = (100, 100, 30, 12)
        widget.edge = 'left'
        with patch('widget.webbrowser.open') as open_browser:
            widget.end_drag(SimpleNamespace(x_root=101, y_root=100))
        open_browser.assert_called_once_with('https://chatgpt.com/')
        self.assertEqual(widget.edge, 'left')

    def test_drag_does_not_open_browser(self):
        widget = Widget.__new__(Widget)
        widget.drag = (10, 10)
        widget.drag_start = (100, 100, 30, 12)
        widget.root = SimpleNamespace(winfo_rootx=lambda: 100, winfo_rooty=lambda: 100,
                                      winfo_width=lambda: 220, winfo_height=lambda: 73)
        with patch('widget.webbrowser.open') as open_browser, \
                patch('widget.monitor_bounds', return_value=(0, 0, 1920, 1080)):
            widget.end_drag(SimpleNamespace(x_root=110, y_root=100))
        open_browser.assert_not_called()


if __name__ == '__main__':
    unittest.main()
