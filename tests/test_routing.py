import subprocess
import sys
import unittest
from pathlib import Path


class RoutingTests(unittest.TestCase):
    def test_real_dispatcher_in_isolated_process(self):
        # У Router один родитель. Отдельный процесс не привязывает глобальные роутеры
        # к тестовому Dispatcher и позволяет повторять тесты в одном сеансе IDE.
        result = subprocess.run(
            [sys.executable, '-c', "import runpy; runpy.run_path('tests/routing_check.py', run_name='__main__')"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
