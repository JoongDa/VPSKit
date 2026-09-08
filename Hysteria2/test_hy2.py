import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('vpskit_hy2', Path(__file__).with_name('hy2.py'))
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class VPSKitTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for name, path in {
            'CONFIG_DIR': 'config', 'SSL_DIR': 'config/ssl', 'AGREE_FILE': 'config/agree.txt',
            'HY_CONFIG': 'server/config.yaml',
            'NODE_FILE': 'config/node.json', 'LINKS_FILE': 'config/links.txt',
            'MIHOMO_FILE': 'config/mihomo.yaml', 'SINGBOX_FILE': 'config/sing-box.json',
            'SURGE_FILE': 'config/surge.conf', 'SUBSCRIPTION_FILE': 'config/subscription.json',
            'NGINX_TEMPLATE': 'config/subscription.nginx.conf',
            'SUBSCRIPTION_DIR': 'web/subscription', 'SHORTCUT_FILE': 'bin/hy2',
            'INSTALLED_SCRIPT': 'lib dir/hy2.py',
        }.items():
            self.stack.enter_context(patch.object(app, name, self.root / path))
        self.chown = self.stack.enter_context(patch.object(app.os, 'chown', create=True))
        self.stack.enter_context(redirect_stdout(io.StringIO()))

    def exports(self):
        app.CONFIG_DIR.mkdir()
        for name, path in app.subscription_sources().items():
            path.write_text('test-content-' + name, encoding='utf-8')
        app.NODE_FILE.write_text('DO_NOT_PUBLISH_DNS_TOKEN')
        app.SSL_DIR.mkdir()
        (app.SSL_DIR / 'server.key').write_text('DO_NOT_PUBLISH_PRIVATE_KEY')
        self.stack.enter_context(patch.object(app, 'web_group_gid', return_value=33))

    def test_shortcut_is_local_and_forwards_arguments(self):
        with patch.object(app, 'run', side_effect=AssertionError('must not run commands')):
            app.create_shortcut()
        content = app.SHORTCUT_FILE.read_text()
        self.assertEqual(app.INSTALLED_SCRIPT.read_bytes(), Path(app.__file__).read_bytes())
        self.assertIn('"$@"', content)
        self.assertIn('/usr/bin/sudo -- /usr/bin/python3', content)
        self.assertNotIn('curl', content)
        self.assertNotIn('wget', content)
        self.assertNotIn('http', content)
        self.chown.assert_any_call(app.INSTALLED_SCRIPT.parent, 0, 0)
        if os.name == 'posix':
            self.assertEqual(app.SHORTCUT_FILE.stat().st_mode & 0o777, 0o755)
            self.assertEqual(app.INSTALLED_SCRIPT.stat().st_mode & 0o777, 0o644)

    def test_shortcut_from_another_directory_preserves_space_arguments(self):
        shell = shutil.which('sh') or 'C:/Program Files/Git/usr/bin/sh.exe'
        if not Path(shell).is_file():
            self.skipTest('POSIX shell unavailable')
        app.INSTALLED_SCRIPT.parent.mkdir(parents=True)
        app.INSTALLED_SCRIPT.write_text('import json, sys; print(json.dumps(sys.argv[1:]))')
        content = app.shortcut_content().replace('/usr/bin/id -u', 'printf 0')
        content = content.replace('/usr/bin/python3', shlex.quote(Path(sys.executable).as_posix()))
        wrapper = self.root / 'launcher.sh'
        wrapper.write_text(content, encoding='utf-8', newline='\n')
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        result = subprocess.run([shell, str(wrapper), '--sample', 'a b', '*literal*'],
                                cwd=elsewhere, text=True, capture_output=True, timeout=10, check=True)
        self.assertEqual(json.loads(result.stdout), ['--sample', 'a b', '*literal*'])
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_bad_source_does_not_replace_installed_script(self):
        app.create_shortcut()
        previous = app.INSTALLED_SCRIPT.read_bytes()
        bad = self.root / 'bad.py'
        bad.write_text('invalid python !!!')
        with patch.object(app, '__file__', str(bad)), self.assertRaises(SyntaxError):
            app.create_shortcut()
        self.assertEqual(previous, app.INSTALLED_SCRIPT.read_bytes())

    def test_atomic_install_failure_preserves_previous_file(self):
        path = self.root / 'old'
        path.write_text('old')
        with patch.object(app.os, 'replace', side_effect=OSError('disk error')), self.assertRaises(OSError):
            app.atomic_install(path, 'new', 0o600)
        self.assertEqual(path.read_text(), 'old')
        self.assertFalse(list(self.root.glob('.vpskit-*')))

    def test_declining_consent_does_not_install_shortcut(self):
        with patch.object(app, 'ensure_root'), patch.object(app.sys, 'argv', ['hy2.py']), \
             patch.object(app, 'yes_no', return_value=False), patch.object(app, 'create_shortcut') as shortcut, \
             patch.object(app, 'ensure_dirs') as dirs, self.assertRaises(SystemExit):
            app.main()
        shortcut.assert_not_called()
        dirs.assert_not_called()

    def test_old_acknowledgement_still_installs_shortcut(self):
        app.AGREE_FILE.parent.mkdir()
        app.AGREE_FILE.touch()
        with patch.object(app, 'ensure_root'), patch.object(app, 'ensure_dirs'), \
             patch.object(app.sys, 'argv', ['hy2.py', '--install-shortcut']), \
             patch.object(app, 'yes_no', side_effect=AssertionError('must not ask')), \
             patch.object(app, 'create_shortcut') as shortcut:
            app.main()
        shortcut.assert_called_once()

    def test_subscription_allowlist_and_stable_urls(self):
        self.exports()
        app.prepare_subscription('sub.xiexie25.com')
        initial = app.read_subscription_settings()
        app.prepare_subscription('sub.xiexie25.com')
        self.assertEqual(initial, app.read_subscription_settings())
        self.assertEqual(set(p.name for p in app.SUBSCRIPTION_DIR.iterdir()),
                         set(app.subscription_sources()) | {'base64.txt'})
        published = b''.join(p.read_bytes() for p in app.SUBSCRIPTION_DIR.iterdir())
        self.assertNotIn(b'DO_NOT_PUBLISH', published)
        self.assertEqual(base64.b64decode((app.SUBSCRIPTION_DIR / 'base64.txt').read_bytes()),
                         app.LINKS_FILE.read_bytes())
        self.assertTrue((app.SUBSCRIPTION_DIR / 'surge.conf').read_text().startswith(
            '#!MANAGED-CONFIG https://sub.xiexie25.com/s/'))
        self.chown.assert_any_call(app.SUBSCRIPTION_DIR, 0, 33)
        if os.name == 'posix':
            self.assertEqual(app.SUBSCRIPTION_DIR.stat().st_mode & 0o777, 0o750)
            self.assertEqual((app.SUBSCRIPTION_DIR / 'links.txt').stat().st_mode & 0o777, 0o640)

    def test_nginx_has_only_exact_file_routes_and_no_caching(self):
        self.exports()
        app.prepare_subscription('sub.xiexie25.com')
        content = app.NGINX_TEMPLATE.read_text()
        self.assertEqual(content.count('location = /s/'), 5)
        self.assertIn('location / { return 404; }', content)
        self.assertIn('private, no-store', content)
        self.assertIn('access_log off;', content)
        self.assertNotIn(str(app.CONFIG_DIR), content)
        self.assertNotIn('node.json', content)

    def test_subscription_refresh_keeps_url_and_reads_latest_export(self):
        self.exports()
        app.prepare_subscription('sub.xiexie25.com')
        before = app.SUBSCRIPTION_FILE.read_bytes()
        app.LINKS_FILE.write_text('hysteria2://NEW-password@example.com:443')
        app.sync_subscription_files()
        self.assertEqual(before, app.SUBSCRIPTION_FILE.read_bytes())
        self.assertEqual((app.SUBSCRIPTION_DIR / 'links.txt').read_bytes(), app.LINKS_FILE.read_bytes())

    def test_missing_export_does_not_enable_subscription(self):
        self.exports()
        app.SURGE_FILE.unlink()
        with self.assertRaises(ValueError):
            app.prepare_subscription('sub.xiexie25.com')
        self.assertFalse(app.SUBSCRIPTION_FILE.exists())

    def test_invalid_domain_and_token_cannot_inject_nginx_routes(self):
        self.exports()
        for domain in ('x.com;}', 'https://sub.xiexie25.com', '../x.com', 'x.com\nroot /;'):
            with self.assertRaises(ValueError):
                app.prepare_subscription(domain)
        app.SUBSCRIPTION_FILE.write_text(json.dumps({'domain': 'sub.xiexie25.com', 'token': '../key'}))
        with self.assertRaises(ValueError):
            app.sync_subscription_files()

    def test_export_triggers_subscription_refresh(self):
        self.exports()
        app.SUBSCRIPTION_FILE.touch()
        with patch.object(app, 'ensure_dirs'), patch.object(app, 'build_hy2_uri', return_value='link'), \
             patch.object(app, 'build_mihomo_config', return_value='mihomo'), \
             patch.object(app, 'build_singbox_config', return_value='{}'), \
             patch.object(app, 'build_surge_config', return_value='surge'), \
             patch.object(app, 'sync_subscription_files') as sync:
            app.export_client_configs({'congestion': {'mode': 'bbr'}}, show_qr=False)
        sync.assert_called_once()

    def test_local_export_without_opt_in_never_prepares_or_syncs_subscription(self):
        self.exports()
        with patch.object(app, 'ensure_dirs'), patch.object(app, 'build_hy2_uri', return_value='link'), \
             patch.object(app, 'build_mihomo_config', return_value='mihomo'), \
             patch.object(app, 'build_singbox_config', return_value='{}'), \
             patch.object(app, 'build_surge_config', return_value='surge'), \
             patch.object(app, 'sync_subscription_files') as sync, \
             patch.object(app, 'prepare_subscription') as prepare:
            app.export_client_configs({'congestion': {'mode': 'bbr'}}, show_qr=False)
        sync.assert_not_called()
        prepare.assert_not_called()
        self.assertFalse(app.SUBSCRIPTION_FILE.exists())
        self.assertFalse(app.SUBSCRIPTION_DIR.exists())
        self.assertFalse(app.NGINX_TEMPLATE.exists())

    def test_menu_view_sync_or_return_does_not_enable_subscription(self):
        with patch('builtins.input', side_effect=['2', '3', '']), \
             patch.object(app, 'prepare_subscription') as prepare, \
             patch.object(app, 'sync_subscription_files') as sync:
            app.subscription_menu()
        prepare.assert_not_called()
        sync.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_menu_explicit_setup_generates_subscription(self):
        self.exports()
        with patch('builtins.input', side_effect=['1', 'sub.xiexie25.com', '0']):
            app.subscription_menu()
        self.assertEqual(app.read_subscription_settings()['domain'], 'sub.xiexie25.com')
        self.assertTrue(app.NGINX_TEMPLATE.is_file())
        self.assertTrue((app.SUBSCRIPTION_DIR / 'mihomo.yaml').is_file())

    def test_main_has_separate_subscription_entry(self):
        with patch.object(app, 'ensure_root'), patch.object(app, 'ensure_dirs'), \
             patch.object(app, 'agree_treaty'), patch.object(app, 'create_shortcut'), \
             patch.object(app, 'clear'), patch.object(app.sys, 'argv', ['hy2.py']), \
             patch('builtins.input', side_effect=['5', '0']), \
             patch.object(app, 'subscription_menu') as menu:
            app.main()
        menu.assert_called_once()

    def test_disable_removes_only_subscription_and_preserves_node_exports(self):
        self.exports()
        app.prepare_subscription('sub.xiexie25.com')
        original = {path: path.read_bytes() for path in app.subscription_sources().values()}
        extra = app.SUBSCRIPTION_DIR / 'unrelated.txt'
        extra.write_text('keep')
        with patch('builtins.input', side_effect=['4', '0']), patch.object(app, 'yes_no', return_value=True):
            app.subscription_menu()
        self.assertFalse(app.SUBSCRIPTION_FILE.exists())
        self.assertFalse(app.NGINX_TEMPLATE.exists())
        self.assertEqual(list(app.SUBSCRIPTION_DIR.iterdir()), [extra])
        self.assertEqual({path: path.read_bytes() for path in original}, original)
        self.assertTrue(app.NODE_FILE.is_file())
        self.assertTrue((app.SSL_DIR / 'server.key').is_file())
        app.sync_subscription_files()
        self.assertEqual(list(app.SUBSCRIPTION_DIR.iterdir()), [extra])

    def test_declining_disable_keeps_subscription(self):
        self.exports()
        app.prepare_subscription('sub.xiexie25.com')
        with patch('builtins.input', side_effect=['4', '0']), patch.object(app, 'yes_no', return_value=False):
            app.subscription_menu()
        self.assertTrue(app.SUBSCRIPTION_FILE.exists())
        self.assertTrue((app.SUBSCRIPTION_DIR / 'links.txt').exists())

    def test_view_displays_saved_link_and_qr_without_regenerating(self):
        self.exports()
        uri = 'hysteria2://original%23password@[2001:db8::1]:443/?sni=example.com#HY2'
        app.LINKS_FILE.write_text(uri + '\n')
        app.HY_CONFIG.parent.mkdir()
        app.HY_CONFIG.write_text('listen: :443\n')
        original = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        output = io.StringIO()
        with redirect_stdout(output), patch.object(app, 'command_exists', return_value=True), \
             patch.object(app.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'QR-DEMO\n', '')) as qr, \
             patch.object(app, 'export_client_configs') as export, \
             patch.object(app, 'sync_subscription_files') as sync:
            app.show_configs()
        self.assertIn(uri, output.getvalue())
        self.assertIn('QR-DEMO', output.getvalue())
        self.assertIn('listen: :443', output.getvalue())
        self.assertEqual(qr.call_args.kwargs['input'], uri)
        self.assertNotIn(uri, qr.call_args.args[0])
        self.assertEqual({p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}, original)
        export.assert_not_called()
        sync.assert_not_called()

    def test_missing_qr_tool_keeps_link_and_explains_installation(self):
        output = io.StringIO()
        with redirect_stdout(output), patch.object(app, 'command_exists', return_value=False), \
             patch.object(app.subprocess, 'run') as run:
            app.show_share_link('hysteria2://test@example.com:443')
        self.assertIn('hysteria2://test@example.com:443', output.getvalue())
        self.assertIn('apt-get install -y qrencode', output.getvalue())
        run.assert_not_called()

    def test_qr_failure_or_timeout_keeps_view_usable(self):
        for result in (subprocess.CompletedProcess([], 1, '', 'failed'),
                       subprocess.TimeoutExpired('qrencode', 10)):
            output = io.StringIO()
            kwargs = {'side_effect': result} if isinstance(result, Exception) else {'return_value': result}
            with redirect_stdout(output), patch.object(app, 'command_exists', return_value=True), \
                 patch.object(app.subprocess, 'run', **kwargs):
                app.show_share_link('hysteria2://test@example.com:443')
            self.assertIn('可复制上面的链接导入', output.getvalue())

    def test_view_with_missing_link_does_not_invent_or_export_credentials(self):
        output = io.StringIO()
        with redirect_stdout(output), patch.object(app, 'show_share_link') as show, \
             patch.object(app, 'export_client_configs') as export:
            app.show_configs()
        self.assertIn('未找到已保存的 HY2 分享链接', output.getvalue())
        show.assert_not_called()
        export.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
