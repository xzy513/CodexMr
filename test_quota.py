import unittest
from unittest.mock import patch, MagicMock
import quota
from quota import windows


class WindowsTest(unittest.TestCase):
    def test_multi_bucket_and_missing_windows(self):
        result = {'rateLimitsByLimitId': {'codex': {'primary': {'usedPercent': 25}, 'secondary': None},
                                         'other': {'limitName': '其他', 'secondary': {'usedPercent': 90}}}}
        self.assertEqual([(label, data['usedPercent']) for label, data in windows(result)],
                         [('codex', 25), ('其他', 90)])

    def test_single_bucket_and_empty(self):
        self.assertEqual(windows({'rateLimits': {'primary': {'usedPercent': 0}}})[0][0], 'codex')
        self.assertEqual(windows({}), [])

    def test_bundled_codex_and_login(self):
        with patch.object(quota.sys, 'frozen', True, create=True), \
                patch.object(quota.sys, '_MEIPASS', 'bundle', create=True), \
                patch.object(quota.Path, 'is_file', return_value=True):
            command = quota.codex_command()
        self.assertEqual(command[-1], 'app-server')
        self.assertTrue(command[0].endswith('codex.exe'))
        with patch('quota.codex_command', return_value=['codex.exe', 'app-server']), \
                patch('quota.codex_env', return_value={'CODEX_HOME': 'isolated'}), \
                patch('quota.subprocess.run', return_value=MagicMock(returncode=0)) as run:
            self.assertTrue(quota.login_status())
            quota.login()
        self.assertEqual(run.call_args.args[0], ['codex.exe', 'login'])
        self.assertEqual(run.call_args.kwargs['env'], {'CODEX_HOME': 'isolated'})


if __name__ == '__main__':
    unittest.main()
