import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import vdm


class RestorePlacementTests(unittest.TestCase):
    def test_restore_moves_existing_singleton_window_to_target(self):
        manager = vdm.VDM.__new__(vdm.VDM)
        manager.sessions = {"2": [r"C:\Apps\Example\example.exe"]}
        manager._launch_watches = []
        manager.move_window = Mock()

        existing = SimpleNamespace(hwnd=101)
        windows = [(existing, 1, r"C:\Apps\Example\example.exe", "Example")]
        current = SimpleNamespace(number=2)

        with patch.object(vdm, "movable_windows", return_value=windows), \
                patch.object(vdm.VirtualDesktop, "current",
                             return_value=current), \
                patch.object(vdm.os.path, "exists", return_value=True), \
                patch.object(vdm.subprocess, "Popen") as popen:
            manager.restore(2)

        manager.move_window.assert_called_once_with(101, 2)
        popen.assert_not_called()

    def test_new_window_from_restore_is_forced_to_launch_desktop(self):
        manager = vdm.VDM.__new__(vdm.VDM)
        manager._launch_watches = [{
            "exe": vdm.os.path.normcase(
                vdm.os.path.abspath(r"C:\Apps\Example\example.exe")),
            "target": 2,
            "known": {100},
            "until": time.monotonic() + 5,
        }]
        manager.move_window = Mock()

        new_window = SimpleNamespace(hwnd=101)
        windows = [(new_window, 1, r"C:\Apps\Example\example.exe",
                    "Example response")]

        with patch.object(vdm, "movable_windows", return_value=windows):
            manager.enforce_launch_desktops()

        manager.move_window.assert_called_once_with(101, 2)
        self.assertIn(101, manager._launch_watches[0]["known"])


if __name__ == "__main__":
    unittest.main()
