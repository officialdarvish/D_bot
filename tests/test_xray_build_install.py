"""Exercise the real installer with valid ZIPs and controlled HTTP failures."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(all(shutil.which(c) for c in ('sh','bash','unzip','timeout','install')), 'Linux build tools required')
class XrayInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        fakebin = self.root/'bin'; fakebin.mkdir()
        curl = fakebin/'curl'
        curl.write_text('#!'+sys.executable+'\n'+'''
import json,os,shutil,sys
from pathlib import Path
log=Path(os.environ['FAKE_LOG'])
previous=log.read_text().splitlines() if log.exists() else []
args=sys.argv[1:]
with log.open('a') as f:f.write(json.dumps(args)+'\\n')
mode=os.environ.get('FAKE_MODES','valid').split(',')
action=mode[min(len(previous),len(mode)-1)]
if action=='fail':
 print('curl: (22) The requested URL returned error: 503',file=sys.stderr)
 sys.exit(22)
out=Path(args[args.index('--output')+1])
if action=='corrupt':out.write_bytes(b'truncated ZIP')
else:shutil.copyfile(os.environ['FAKE_ARCHIVE'],out)
''')
        curl.chmod(0o755)
        sleep=fakebin/'sleep';sleep.write_text('#!/bin/sh\nexit 0\n');sleep.chmod(0o755)
        self.archive=self.root/'official-test.zip';self.write_archive()
        self.env={**os.environ,'PATH':str(fakebin)+os.pathsep+os.environ['PATH'],
                  'XRAY_VERSION':'26.9.9','TARGETARCH':'arm64','XRAY_CACHE_DIR':str(self.root/'cache'),
                  'XRAY_LOCAL_DIR':str(self.root/'local'),'XRAY_INSTALL_PATH':str(self.root/'installed/xray'),
                  'FAKE_LOG':str(self.root/'calls.jsonl'),'FAKE_ARCHIVE':str(self.archive)}

    def write_archive(self,version='26.9.9'):
        with ZipFile(self.archive,'w') as z:z.writestr('xray',f'#!/bin/sh\necho "Xray {version} (installer test)"\n')

    def run_install(self,**env):
        return subprocess.run(['sh',str(ROOT/'scripts/install-xray.sh')],env={**self.env,**env},capture_output=True,text=True,timeout=8)

    def calls(self):
        p=Path(self.env['FAKE_LOG'])
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    def test_success_then_cache_hit_has_no_network_even_during_upstream_failure(self):
        first=self.run_install();self.assertEqual(first.returncode,0,first.stderr)
        second=self.run_install(FAKE_MODES='fail');self.assertEqual(second.returncode,0,second.stderr)
        self.assertIn('Reused cached archive',second.stdout)
        self.assertEqual(len(self.calls()),1)
        self.assertTrue(os.access(self.env['XRAY_INSTALL_PATH'],os.X_OK))

    def test_http_503_stops_after_two_bounded_attempts(self):
        r=self.run_install(FAKE_MODES='fail')
        self.assertNotEqual(r.returncode,0)
        self.assertEqual(len(self.calls()),2)
        self.assertFalse(Path(self.env['XRAY_INSTALL_PATH']).exists())
        self.assertFalse(list((self.root/'cache').rglob('*.zip')))
        for args in self.calls():
            for flag,value in [('--connect-timeout','8'),('--max-time','60'),('--retry','0'),('--speed-time','15')]:
                self.assertEqual(args[args.index(flag)+1],value)
        self.assertIn('XRAY_SOURCE=image',r.stderr)

    def test_transient_503_recovers(self):
        r=self.run_install(FAKE_MODES='fail,valid');self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(len(self.calls()),2)

    def test_corrupt_download_is_not_cached_and_can_recover(self):
        r=self.run_install(FAKE_MODES='corrupt,valid');self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(len(self.calls()),2)
        self.assertEqual((self.root/'cache/26.9.9/Xray-linux-arm64-v8a.zip').read_bytes(),self.archive.read_bytes())

    def test_local_archive_needs_no_http(self):
        path=self.root/'local/26.9.9/Xray-linux-arm64-v8a.zip';path.parent.mkdir(parents=True);shutil.copyfile(self.archive,path)
        r=self.run_install(FAKE_MODES='fail');self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('no network',r.stdout);self.assertEqual(self.calls(),[])

    def test_invalid_local_archive_fails_without_silent_network_fallback(self):
        path=self.root/'local/26.9.9/Xray-linux-arm64-v8a.zip';path.parent.mkdir(parents=True);path.write_bytes(b'broken')
        r=self.run_install();self.assertNotEqual(r.returncode,0);self.assertEqual(self.calls(),[])

    def test_wrong_version_cannot_be_installed_or_cached(self):
        self.write_archive('0.0.1')
        r=self.run_install();self.assertNotEqual(r.returncode,0)
        self.assertFalse(Path(self.env['XRAY_INSTALL_PATH']).exists())
        self.assertFalse(list((self.root/'cache').rglob('*.zip')))

    def test_invalid_cache_is_replaced(self):
        path=self.root/'cache/26.9.9/Xray-linux-arm64-v8a.zip';path.parent.mkdir(parents=True);path.write_bytes(b'broken')
        r=self.run_install();self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(len(self.calls()),1)
        self.assertEqual(path.read_bytes(),self.archive.read_bytes())

    def test_architecture_maps_to_official_asset(self):
        for arch,asset in [('amd64','64'),('arm64','arm64-v8a'),('arm','arm32-v7a')]:
            with self.subTest(arch=arch):
                r=self.run_install(TARGETARCH=arch);self.assertEqual(r.returncode,0,r.stderr)
                self.assertTrue(any(f'/Xray-linux-{asset}.zip' in arg for args in self.calls() for arg in args))
        count=len(self.calls());r=self.run_install(TARGETARCH='unsupported')
        self.assertNotEqual(r.returncode,0);self.assertEqual(len(self.calls()),count)

    def test_update_build_failure_returns_before_health_check(self):
        source=(ROOT/'scripts/dbot-control.sh').read_text()
        function=re.search(r'update_app\(\)\{.*?\n\}\n(?=\nuninstall_app)',source,re.S).group(0)
        app=self.root/'app';app.mkdir()
        shell='''set -e
APP_DIR="$1"
COMPOSE=fake_compose
C_RED= C_NC=
cd_app(){ cd "$APP_DIR"; }
install_manager_self(){ :; }
fake_compose(){ echo "MOCK_COMPOSE:$*"; return 7; }
wait_for_api_health(){ echo 'UNEXPECTED_HEALTH'; return 0; }
'''+function+'''
if update_app; then echo 'UNEXPECTED_SUCCESS'; else exit 9; fi
'''
        r=subprocess.run(['bash','-c',shell,'test',str(app)],capture_output=True,text=True)
        self.assertEqual(r.returncode,9,r.stderr)
        self.assertIn('MOCK_COMPOSE:up -d --build',r.stdout)
        self.assertNotIn('UNEXPECTED_',r.stdout)

    def test_default_docker_route_uses_pinned_image_not_archive_download(self):
        docker=(ROOT/'Dockerfile').read_text()
        self.assertIn('ARG XRAY_SOURCE=image',docker)
        self.assertIn('ghcr.io/xtls/xray-core:26.9.9@sha256:',docker)
        self.assertIn('FROM xray-${XRAY_SOURCE} AS xray-source',docker)
        self.assertIn('COPY --from=xray-source /usr/local/bin/xray /usr/local/bin/xray',docker)
        self.assertNotIn('curl -fL --retry 4',docker)
        self.assertLess(docker.index('AS xray-archive'),docker.index('COPY requirements.txt'))
        self.assertIn('!build/xray/**/*.zip',(ROOT/'.dockerignore').read_text())
        compose=(ROOT/'docker-compose.yml').read_text()
        import yaml
        services=yaml.safe_load(compose)['services']
        self.assertEqual(services['api']['image'],services['bot']['image'])
        self.assertIn('build',services['api'])
        self.assertNotIn('build',services['bot'])
        self.assertIn('XRAY_SOURCE: ${XRAY_SOURCE:-image}',compose)

if __name__=='__main__':unittest.main()
