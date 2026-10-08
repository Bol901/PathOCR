import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pathocr.app import create_app
from pathocr.runtime import FILES


class StartupTests(unittest.TestCase):
    def test_launch_automatically_prepares_engine(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            app = create_app(Path(directory), 'test-token')
            try:
                with patch.object(app.state.runtime, 'setup') as setup:
                    with TestClient(app) as client:
                        self.assertEqual(client.get('/?token=test-token').status_code, 200)
                        setup.assert_called_once_with()
            finally:
                app.state.store.db.close()

    def test_setup_downloads_defaults_but_preserves_custom_files(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            app = create_app(Path(directory), auto_setup=False)
            runtime = app.state.runtime
            store = app.state.store
            server = Path(directory)/'engine'
            server.write_bytes(b'local engine')
            settings = store.settings()
            settings['server_path'] = str(server)
            store.save_settings(settings)
            try:
                with patch('pathocr.runtime.download') as download, patch.object(runtime, 'ensure') as ensure:
                    runtime._setup()
                    self.assertEqual(download.call_count, 2)
                    self.assertEqual({call.args[3] for call in download.call_args_list}, set(FILES.values()))
                    ensure.assert_called_once_with()
                for key in ('model_path', 'mmproj_path'):
                    target = Path(directory)/key
                    target.write_bytes(b'custom model')
                    settings[key] = str(target)
                store.save_settings(settings)
                with patch('pathocr.runtime.download') as download, patch.object(runtime, 'ensure'):
                    runtime._setup()
                    download.assert_not_called()
                self.assertEqual(Path(settings['model_path']).read_bytes(), b'custom model')
            finally:
                runtime.close()
                store.db.close()


if __name__ == '__main__':
    unittest.main()
