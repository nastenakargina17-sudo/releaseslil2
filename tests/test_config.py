import importlib
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import app.config


class ConfigTests(unittest.TestCase):
    def test_uploads_directory_can_be_configured_for_persistent_storage(self) -> None:
        with patch.dict(os.environ, {"UPLOADS_DIR": "/app/data/uploads"}):
            config = importlib.reload(app.config)

            self.assertEqual(config.UPLOADS_DIR, Path("/app/data/uploads"))

        importlib.reload(app.config)
