import os
import subprocess
import sys
import unittest
from pathlib import Path


class ImportTest(unittest.TestCase):
    def test_all_modules_import_without_local_configuration_or_credentials(self):
        root = Path(__file__).resolve().parents[1]
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHON_DOTENV_DISABLED": "1",
            "CODEBASE_CONFIGS_PATH": "/missing-codebase-config.json",
        }
        result = subprocess.run(
            [sys.executable, "-c", """
import importlib
import pkgutil
import app
import main
for module in pkgutil.walk_packages(app.__path__, 'app.'):
    importlib.import_module(module.name)
"""],
            cwd=root, env=environment, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
