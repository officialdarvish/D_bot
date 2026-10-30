import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('runtime_file_check', ROOT/'scripts/check_runtime_files.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def release_files(tmp_path):
    for name in checker.REQUIRED:
        path = tmp_path/name
        path.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/name,path)
    return tmp_path


def test_complete_source_passes_without_credentials_or_database():
    result=subprocess.run([sys.executable,str(ROOT/'scripts/check_runtime_files.py')],env={},capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_exact_missing_ownership_module_from_report_is_detected(tmp_path):
    root=release_files(tmp_path)
    (root/'app/services/service_ownership.py').unlink()
    assert checker.check_runtime_files(root)==['Missing required file: app/services/service_ownership.py']
    result=subprocess.run([sys.executable,str(ROOT/'scripts/check_runtime_files.py'),'--root',str(root)],capture_output=True,text=True)
    assert result.returncode==1 and 'app/services/service_ownership.py' in result.stderr


def test_empty_or_outdated_helper_is_detected(tmp_path):
    root=release_files(tmp_path)
    (root/'app/services/service_ownership.py').write_text('# incomplete upload\n')
    assert any('Incomplete or outdated' in error for error in checker.check_runtime_files(root))


def test_broken_python_is_detected(tmp_path):
    root=release_files(tmp_path)
    (root/'app/services/receipt_status.py').write_text('def invalid(\n')
    assert checker.check_runtime_files(root)==['Unreadable or invalid Python file: app/services/receipt_status.py']


def test_check_is_after_both_runtime_copy_operations():
    docker=(ROOT/'Dockerfile').read_text()
    assert docker.index('COPY app ./app')<docker.index('RUN python scripts/check_runtime_files.py')
    assert docker.index('COPY scripts ./scripts')<docker.index('RUN python scripts/check_runtime_files.py')
