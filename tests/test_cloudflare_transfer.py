import shutil
import subprocess
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.palette import ThemeMode
from app.config import AppConfig
from app.services.cloudflare_transfer import DEFAULT_ENDPOINT, DEFAULT_SERVICE_TOKEN, TransferClient, TransferError
from app.tools.network_lan_remote import LanRemoteTool

ROOT = Path(__file__).resolve().parents[1]


class CloudflareProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = subprocess.Popen([shutil.which('node'), str(ROOT / 'tests/cloudflare_test_server.mjs')], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        cls.endpoint = f'http://127.0.0.1:{cls.server.stdout.readline().strip()}'

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.server.stdout.close()

    def client(self, name='Alex'):
        return TransferClient(self.endpoint, 'test-service-token', name)

    def test_two_clients_chat_and_cursor(self):
        alice, bob = self.client(), self.client('민지')
        alice.create()
        bob.join(alice.invitation)
        alice.send('안녕하세요 👍')
        self.assertEqual(bob.events()[0]['text'], '안녕하세요 👍')
        self.assertEqual(bob.events(), [])
        bob.send('반갑습니다')
        self.assertEqual([e['text'] for e in alice.events()], ['안녕하세요 👍', '반갑습니다'])

    def test_binary_file_roundtrip_and_progress(self):
        alice, bob = self.client(), self.client('Bob')
        alice.create()
        bob.join(alice.invitation)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / '한글 데이터.bin'
            source.write_bytes(bytes(range(256)) * 1000)
            upload, download = [], []
            alice.upload(source, lambda *v: upload.append(v))
            event = bob.events()[0]
            destination = Path(directory) / 'received.bin'
            bob.download(event['file'], destination, event['size'], lambda *v: download.append(v))
            self.assertEqual(source.read_bytes(), destination.read_bytes())
            self.assertEqual(upload[-1], (source.stat().st_size,) * 2)
            self.assertEqual(download[-1], upload[-1])

    def test_wrong_keys_and_service_tokens(self):
        alice, bob = self.client(), self.client('Bob')
        alice.create()
        with self.assertRaises(TransferError):
            bob.join(alice.room + ':' + '0' * 64)
        with self.assertRaises(TransferError):
            TransferClient(self.endpoint, 'wrong').create()

    def test_room_isolation(self):
        alice, bob = self.client(), self.client('Bob')
        alice.create()
        bob.create()
        alice.send('private')
        self.assertEqual(bob.events(), [])

    def test_endpoint_validation(self):
        for endpoint in ['http://example.com', 'https://a@host', 'https://host/path', 'https://host?token=x', 'ftp://host']:
            with self.subTest(endpoint=endpoint), self.assertRaises(TransferError):
                TransferClient(endpoint, 'token')

    def test_invitation_and_message_limits(self):
        client = self.client()
        with self.assertRaises(TransferError):
            client.join('room-name')
        client.create()
        for text in ['', ' ' * 2, 'a' * 4001]:
            with self.assertRaises(TransferError):
                client.send(text)

    def test_cancelled_download_preserves_destination(self):
        client = self.client()
        client.create()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.bin'
            source.write_bytes(b'x' * 200000)
            client.upload(source, lambda *_: None)
            event = client.events()[0]
            destination = Path(directory) / 'existing.bin'
            destination.write_bytes(b'original')
            with self.assertRaises(TransferError):
                client.download(event['file'], destination, event['size'], lambda *_: client.cancel.set())
            self.assertEqual(destination.read_bytes(), b'original')
            self.assertEqual(list(Path(directory).glob('*.part')), [])

    def test_invalid_size_and_cancelled_request(self):
        client = self.client()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'empty'
            source.touch()
            with self.assertRaises(TransferError):
                client.upload(source, lambda *_: None)
        client.cancel.set()
        with self.assertRaises(TransferError):
            client.create()


class CloudflareViewTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry('1260x820')
        self.errors = []
        self.root.report_callback_exception = lambda _, error, __: self.errors.append(error)
        self.app = SimpleNamespace(dark_mode=ThemeMode.DARK)
        self.view = LanRemoteTool(self.root, self.app)
        self.view.pack(fill='both', expand=True)
        self.root.update()

    def tearDown(self):
        self.view.destroy()
        self.root.destroy()

    def test_layout_and_narrow_resize(self):
        self.assertEqual(self.view.file_panel.grid_info()['row'], 0)
        self.assertGreater(self.view.chat_panel.winfo_width(), self.view.file_panel.winfo_width())
        self.assertGreater(self.view.message_entry.winfo_width(), 100)
        self.assertGreater(self.view.room_entry.winfo_width(), 100)
        self.assertLess(self.view.options_button.winfo_rootx() + self.view.options_button.winfo_width(), self.root.winfo_rootx() + self.root.winfo_width())
        self.root.geometry('880x820')
        self.root.update()
        self.assertEqual(self.view.file_panel.grid_info()['row'], 1)
        self.assertGreater(self.view.message_entry.winfo_width(), 100)
        self.assertLess(self.view.options_button.winfo_rootx() + self.view.options_button.winfo_width(), self.root.winfo_rootx() + self.root.winfo_width())
        self.assertFalse(self.errors)

    def test_stale_events_ignored_after_disconnect(self):
        called = []
        generation = self.view.generation
        self.view.stop()
        self.view.events.put((generation, lambda *_: called.append(True), None, None))
        self.view.after_cancel(self.view.timer)
        self.view._drain()
        self.assertEqual(called, [])

    def test_transfer_filters_disconnect_and_history(self):
        card = self.view._card('sample.zip', 200000, '전송 중')
        self.view._progress(card, 100000, 200000, 50000)
        self.assertEqual(card['bar']['value'], 50)
        self.view.filter_files('완료')
        self.assertFalse(card['frame'].winfo_manager())
        self.view.stop()
        self.assertEqual(card['state'], '실패')
        self.view._log('test record')
        self.assertIn('test record', self.view.history.get('1.0', 'end'))

    def test_options_and_themes(self):
        self.view.options()
        self.root.update()
        self.assertTrue(self.view.options_window.winfo_exists())
        for theme in (ThemeMode.LIGHT, ThemeMode.GREEN):
            other = LanRemoteTool(self.root, SimpleNamespace(dark_mode=theme))
            other.destroy()
        self.assertFalse(self.errors)

    def test_files_tab_does_not_open_picker(self):
        with patch('app.tools.network_lan_remote.filedialog.askopenfilenames') as picker:
            self.view.show_tab('files')
            picker.assert_not_called()

    def test_default_server_restore_and_options_save_excludes_token(self):
        self.assertEqual(self.view.endpoint.get(), DEFAULT_ENDPOINT)
        self.assertEqual(self.view.token.get(), DEFAULT_SERVICE_TOKEN)
        self.view.endpoint.set('https://custom.example')
        self.view.token.set('custom-key')
        self.view._restore_defaults()
        self.view.options()
        self.app.config_store = SimpleNamespace(set_many=lambda values: saved.update(values))
        saved = {}
        self.view._save_options(self.view.options_window)
        self.assertEqual(set(saved), {('cloudflare_transfer', 'endpoint'), ('cloudflare_transfer', 'name')})
        self.assertEqual(saved[('cloudflare_transfer', 'endpoint')], DEFAULT_ENDPOINT)
        self.assertEqual(self.view.token.get(), DEFAULT_SERVICE_TOKEN)

    def test_saved_custom_endpoint_never_receives_builtin_key(self):
        for endpoint, expected_key in [('https://custom.example', ''), ('', DEFAULT_SERVICE_TOKEN), ('  ', DEFAULT_SERVICE_TOKEN), (None, DEFAULT_SERVICE_TOKEN), (DEFAULT_ENDPOINT + '/', DEFAULT_SERVICE_TOKEN)]:
            config = AppConfig()
            config.data['cloudflare_transfer'] = {'endpoint': endpoint}
            other = LanRemoteTool(self.root, SimpleNamespace(dark_mode=ThemeMode.DARK, config_store=config))
            try:
                self.assertEqual(other.token.get(), expected_key)
                self.assertTrue(other.endpoint.get())
            finally:
                other.destroy()


if __name__ == '__main__':
    unittest.main()
