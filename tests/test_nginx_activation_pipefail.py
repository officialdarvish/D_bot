"""Exercise real Bash/pipe buffers, using an isolated fake Nginx executable."""
import os
import subprocess
from pathlib import Path
import pytest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/setup_web_ssl.sh'

@pytest.fixture
def harness(tmp_path):
    definitions=SCRIPT.read_text().split('\nDOMAIN="$(normalize_domain "$DOMAIN")"')[0]
    source=tmp_path/'functions.sh';source.write_text(definitions)
    enabled=tmp_path/'sites-enabled'/'d-bot.conf';conf=tmp_path/'conf.d'/'d-bot.conf';available=tmp_path/'sites-available'/'d-bot.conf'
    for p in (enabled,conf,available):p.parent.mkdir()
    available.write_text('server {}\n')
    fake=tmp_path/'fake_nginx.py'
    fake.write_text('''import os,sys,signal
signal.signal(signal.SIGPIPE,signal.SIG_DFL)
mode=os.environ['FAKE_MODE']
if mode=='error':
 print('nginx: [emerg] invalid number of arguments in /etc/nginx/nginx.conf:12',flush=True);sys.exit(1)
if mode=='invalid_with_header':
 print('# configuration file '+os.environ['SITE_ENABLED']+':',flush=True)
 print('nginx: [emerg] invalid directive',flush=True);sys.exit(1)
path=os.environ['SITE_ENABLED'] if mode in ('sites','large','canonical') else os.environ['CONF_D_SITE']
if mode=='canonical':path=os.environ['SITE_AVAILABLE']
if mode!='none' and os.path.islink(path):
 print('# configuration file '+path+':',flush=True)
elif mode=='canonical':
 print('# configuration file '+path+':',flush=True)
else:print('# configuration file /etc/nginx/nginx.conf:',flush=True)
if mode=='large':
 for i in range(1024):os.write(1,b'# many unrelated configuration lines '+b'x'*8192+b'\\n')
''')
    env={**os.environ,'SITE_ENABLED':str(enabled),'CONF_D_SITE':str(conf),'SITE_AVAILABLE':str(available),'FAKE_NGINX':str(fake)}
    prefix='source "$1"\nSITE_ENABLED="$2"; CONF_D_SITE="$3"; SITE_AVAILABLE="$4"\nnginx() { python3 "$FAKE_NGINX"; }\n'
    def run(mode,body='activate_site_config'):
        return subprocess.run(['bash','-c',prefix+body,'test',str(source),str(enabled),str(conf),str(available)],env={**env,'FAKE_MODE':mode},capture_output=True,text=True,timeout=15)
    return run,enabled,conf


def test_old_pipeline_reproduces_sigpipe_but_fixed_activation_succeeds(harness):
    run,enabled,conf=harness
    enabled.symlink_to(enabled.parent.parent/'sites-available'/'d-bot.conf')
    old=run('large','nginx -T 2>&1 | grep -Fq "# configuration file ${SITE_ENABLED}:"')
    assert old.returncode==141 # Found the line, but producer was killed by SIGPIPE.
    fixed=run('large')
    assert fixed.returncode==0,fixed.stderr
    assert enabled.is_symlink() and not conf.exists()
    assert 'sites-enabled' in fixed.stdout


@pytest.mark.parametrize('mode,folder',[('sites','sites-enabled'),('conf','conf.d'),('canonical','sites-enabled')])
def test_supported_include_layouts(harness,mode,folder):
    run,enabled,conf=harness
    result=run(mode)
    assert result.returncode==0,result.stderr
    assert folder in result.stdout
    assert enabled.is_symlink() if folder=='sites-enabled' else conf.is_symlink()
    assert not (enabled.is_symlink() and conf.is_symlink())


@pytest.mark.parametrize('mode',['error','invalid_with_header'])
def test_real_nginx_errors_are_not_reported_as_missing_includes(harness,mode):
    run,enabled,conf=harness
    result=run(mode)
    assert result.returncode!=0
    assert '[emerg]' in result.stderr and 'configuration test failed' in result.stderr
    assert 'does not load' not in result.stderr
    assert not conf.exists() # Never falls back on a real syntax failure.


def test_actually_missing_includes_remain_an_error(harness):
    result=harness[0]('none')
    assert result.returncode!=0
    assert 'does not load' in result.stderr
