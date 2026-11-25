#!/usr/bin/env python3
"""Apply one D BOT domain change on the VPS, outside the API container."""
import argparse
import fcntl
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from app.core.web_domain import normalize_domain

NGINX = Path('/etc/nginx')
MANAGED = ('sites-available/d-bot.conf', 'sites-enabled/d-bot.conf', 'conf.d/d-bot.conf')


def compose():
    if subprocess.run(['docker', 'compose', 'version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        return ['docker', 'compose']
    return ['docker-compose']


def site_environment(source):
    options = {}
    wanted = {'API_PORT', 'NGINX_HTTP_PORT', 'NGINX_HTTPS_PORT', 'LETSENCRYPT_EMAIL'}
    for line in source.splitlines():
        key, sep, value = line.removeprefix('export ').partition('=')
        if sep and key.strip() in wanted:
            words = shlex.split(value, comments=True)
            if len(words) > 1:
                raise ValueError('Invalid VPS port or Certbot email configuration')
            options[key.strip()] = words[0] if words else ''
    return options


def atomic_env(path, content):
    fd, name = tempfile.mkstemp(prefix='.domain-env-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def updated_env(source, values):
    lines = [line for line in source.splitlines() if line.removeprefix('export ').partition('=')[0].strip() not in values]
    lines.extend(f'{key}={value}' for key, value in values.items())
    return '\n'.join(lines) + '\n'


def reload_nginx():
    subprocess.run(['nginx', '-t'], check=True, timeout=15)
    subprocess.run(['nginx', '-s', 'reload'], check=True, timeout=20)


def snapshot_site(directory):
    for name in MANAGED:
        source = NGINX / name
        if source.exists() or source.is_symlink():
            target = directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target, follow_symlinks=False)


def site_state(directory):
    state = {}
    for name in MANAGED:
        path = directory / name
        if path.is_symlink():
            state[name] = ('symlink', os.readlink(path))
        elif path.is_file():
            state[name] = ('file', path.read_bytes())
    return state


def restore_site(directory):
    for name in MANAGED:
        source = directory / name
        target = NGINX / name
        target.unlink(missing_ok=True)
        if source.exists() or source.is_symlink():
            shutil.copy2(source, target, follow_symlinks=False)
    reload_nginx()


def apply(domain, https):
    env_file = APP / '.env'
    source = env_file.read_text(encoding='utf-8')
    options = site_environment(source)
    scheme = 'https' if https else 'http'
    port = int(options.get('NGINX_HTTPS_PORT' if https else 'NGINX_HTTP_PORT') or (443 if https else 80))
    if not 1 <= port <= 65535:
        raise ValueError('Invalid web port')
    authority = domain if port == (443 if https else 80) else f'{domain}:{port}'
    base_url = f'{scheme}://{authority}'
    db_command = compose() + ['exec', '-T', 'api', 'python', '/app/scripts/web_credentials_cli.py']
    # Verify database reachability before changing any live Nginx file.
    subprocess.run(db_command + ['web-url'], cwd=APP, check=True, timeout=20, stdout=subprocess.DEVNULL)
    with tempfile.TemporaryDirectory(prefix='dbot-domain-') as backup:
        directory = Path(backup)
        snapshot_site(directory)
        env_changed = False
        try:
            subprocess.run(['bash', str(APP / 'scripts/setup_web_ssl.sh'), domain, 'switch' if https else 'switch-http'],
                           cwd=APP, env={**os.environ, **options}, check=True)
            values = {'DOMAIN_NAME': domain, 'ENABLE_HTTPS': 'true' if https else 'false', 'PUBLIC_BASE_URL': base_url}
            atomic_env(env_file, updated_env(source, values))
            env_changed = True
            subprocess.run(db_command + ['set-domain', domain, scheme, str(port)], cwd=APP,
                           check=True, capture_output=True, text=True)
        except BaseException:
            try:
                if env_changed:
                    atomic_env(env_file, source)
            except OSError:
                print('[dbot-domain] ERROR: Environment rollback failed. Check the VPS .env file.', file=sys.stderr)
            if site_state(NGINX) != site_state(directory):
                try:
                    restore_site(directory)
                except Exception:
                    print('[dbot-domain] ERROR: Nginx rollback failed. Check nginx -t and the VPS journal.', file=sys.stderr)
                    raise
            raise
    print(f'D BOT website: {base_url}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('domain')
    parser.add_argument('--http', action='store_true')
    args = parser.parse_args()
    domain = normalize_domain(args.domain)
    # Also serialize manual dbot commands and requests from the web panel.
    fd = os.open('/run/lock/d-bot-domain.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another D BOT domain change is running') from None
        apply(domain, not args.http)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        detail = getattr(exc, 'stderr', None)
        if detail:
            print(detail, file=sys.stderr)
        print(f'[dbot-domain] ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
