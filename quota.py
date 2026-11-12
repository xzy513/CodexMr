import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path


def codex_command():
    bundled = Path(getattr(sys, '_MEIPASS', '')) / 'codex-runtime' / 'codex.exe'
    if getattr(sys, 'frozen', False) and bundled.is_file():
        return [str(bundled), 'app-server']
    command = shutil.which('codex.cmd' if os.name == 'nt' else 'codex')
    if not command:
        raise RuntimeError('找不到 Codex CLI，请先安装并登录 Codex。')
    if os.name == 'nt':
        candidates = list((Path(command).parent / 'node_modules' / '@openai' / 'codex').glob(
            'node_modules/@openai/codex-win32-*/vendor/*/bin/codex.exe'))
        if candidates:
            command = str(candidates[0])
        else:
            raise RuntimeError('找不到 Codex 可执行文件，请检查 Codex CLI 安装。')
    return [command, 'app-server']


def codex_env():
    env = os.environ.copy()
    home = Path(env.get('LOCALAPPDATA') or Path.home()) / 'CodexMr'
    home.mkdir(parents=True, exist_ok=True)
    env['CODEX_HOME'] = str(home)
    return env


def login_status():
    result = subprocess.run(codex_command()[:-1] + ['login', 'status'], env=codex_env(),
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=20,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    return result.returncode == 0


def login():
    result = subprocess.run(codex_command()[:-1] + ['login'], env=codex_env(),
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=300,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode != 0:
        raise RuntimeError('登录未完成，请检查网络后重试。')


def read_limits(timeout=20):
    process = subprocess.Popen(codex_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, encoding='utf-8', env=codex_env(),
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    messages = queue.Queue()

    def read_output():
        try:
            for line in process.stdout:
                messages.put(json.loads(line))
        except (ValueError, OSError) as exc:
            messages.put(exc)
        finally:
            messages.put(None)

    threading.Thread(target=read_output, daemon=True).start()

    def send(message):
        process.stdin.write(json.dumps(message) + '\n')
        process.stdin.flush()

    def response(request_id):
        deadline = time.monotonic() + timeout
        while True:
            try:
                message = messages.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty:
                raise RuntimeError('读取超时，请检查网络或 Codex 登录状态。')
            if message is None:
                raise RuntimeError('Codex 服务已退出，请检查登录状态。')
            if isinstance(message, Exception):
                raise RuntimeError('无法读取 Codex 服务响应。') from message
            if message.get('id') == request_id:
                if message.get('error'):
                    raise RuntimeError(message['error'].get('message', '读取限额失败。'))
                return message.get('result', {})

    try:
        send({'id': 1, 'method': 'initialize', 'params': {'clientInfo': {
            'name': 'codex_quota_widget', 'title': 'Codex Quota Widget', 'version': '1.0.0'}}})
        response(1)
        send({'method': 'initialized', 'params': {}})
        send({'id': 2, 'method': 'account/rateLimits/read'})
        return response(2)
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        for stream in (process.stdin, process.stdout):
            stream.close()


def windows(result):
    buckets = result.get('rateLimitsByLimitId') or {}
    if not buckets and result.get('rateLimits'):
        bucket = result['rateLimits']
        buckets = {bucket.get('limitId') or 'codex': bucket}
    rows = []
    for key, bucket in buckets.items():
        if not isinstance(bucket, dict):
            continue
        for name in ('primary', 'secondary'):
            window = bucket.get(name)
            if isinstance(window, dict) and isinstance(window.get('usedPercent'), (int, float)):
                rows.append((bucket.get('limitName') or key, window))
    return rows
