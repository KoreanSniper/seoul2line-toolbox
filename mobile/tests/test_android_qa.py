from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch
from mobile.android_qa import requested
from mobile.build_scripts.android_smoke import validate


class AndroidQAGateTests(unittest.TestCase):
    def request(self, debug=True, enabled=True, run='a'*16, phase=1):
        intent = SimpleNamespace(getBooleanExtra=lambda *_: enabled,getStringExtra=lambda *_:run,getIntExtra=lambda *_:phase)
        activity = SimpleNamespace(getIntent=lambda:intent,getApplicationInfo=lambda:SimpleNamespace(flags=2 if debug else 0))
        module = SimpleNamespace(autoclass=lambda _:SimpleNamespace(mActivity=activity))
        with patch.dict(sys.modules,{'jnius':module}):
            return requested()

    def test_release_and_normal_launch_never_enable_qa(self):
        self.assertIsNone(self.request(debug=False))
        self.assertIsNone(self.request(enabled=False))

    def test_run_identifier_cannot_escape_isolated_directory(self):
        for value in ('../profile','',None,'a'*33,'run-id-with-slashes/a'):
            self.assertIsNone(self.request(run=value))
        self.assertIsNone(self.request(phase=3))

    def test_debug_request_accepts_only_known_phases(self):
        self.assertEqual(self.request(),dict(run='a'*16,phase=1))
        self.assertEqual(self.request(phase=2),dict(run='a'*16,phase=2))

    def test_host_rejects_incomplete_and_failed_native_report(self):
        for report in (dict(status='failed',phase=1),dict(status='passed',phase=1,checks=['android_home_five_tabs'])):
            with self.assertRaises(AssertionError):
                validate(report,1)
        validate(dict(status='passed',phase=2,checks=['real_process_restart_theme_pins_note_audio'],width=1080,height=1900),2)


if __name__ == '__main__':
    unittest.main()
