"""Persisted server inventory with bounded background check concurrency."""
from dataclasses import asdict
import json
from pathlib import Path
import queue
import re
import threading

from moodle_check import CheckResult, check_moodle, normalize_address


class ConflictError(Exception):
    pass


class Registry:
    def __init__(self, directory, checker=check_moodle, workers=6):
        self.path = Path(directory) / 'servers.json'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.jobs = queue.Queue()
        self.checker = checker
        self.revision = 0
        self.rows = []
        self.states = {}
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('format') != 1:
                raise ValueError('Unsupported inventory format')
            self.rows = self.validate_rows(data['servers'])
            self.revision = int(data['revision'])
        for number in range(workers):
            threading.Thread(target=self.run, daemon=True, name=f'http-check-{number}').start()

    @staticmethod
    def validate_rows(rows):
        if not isinstance(rows, list):
            raise ValueError('Ожидается список серверов.')
        result, seen = [], set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('Некорректная строка сервера.')
            key, address = row.get('id'), row.get('address')
            if not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,64}', key) or key in seen:
                raise ValueError('Идентификаторы строк должны быть уникальными.')
            if not isinstance(address, str) or len(address) > 2048:
                raise ValueError('Адрес должен быть строкой до 2048 символов.')
            address = normalize_address(address) if address.strip() else ''
            result.append({'id': key, 'address': address})
            seen.add(key)
        return result

    def snapshot(self):
        with self.lock:
            return {'revision': self.revision, 'servers': [dict(row, **self.states.get(row['id'], {
                'kind': 'idle', 'message': 'Не проверен', 'url': '', 'elapsed_ms': 0,
            })) for row in self.rows]}

    def replace(self, rows, revision):
        rows = self.validate_rows(rows)
        with self.lock:
            if revision != self.revision:
                raise ConflictError('Список изменён в другом окне. Перезагрузите страницу перед сохранением.')
            if rows == self.rows:
                return self.snapshot()
            data = {'format': 1, 'revision': self.revision + 1, 'servers': rows}
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            temporary.replace(self.path)
            previous = {row['id']: row['address'] for row in self.rows}
            self.states = {row['id']: self.states[row['id']] for row in rows
                           if row['id'] in self.states and previous.get(row['id']) == row['address']}
            self.rows = rows
            self.revision += 1
            return self.snapshot()

    def check(self, ids):
        with self.lock:
            rows = {row['id']: row for row in self.rows}
            if not isinstance(ids, list) or not all(isinstance(key, str) and key in rows for key in ids):
                raise ValueError('Сервер не найден. Сначала сохраните список.')
            for key in dict.fromkeys(ids):
                row = rows[key]
                if not row['address'] or self.states.get(key, {}).get('kind') in ('queued', 'checking'):
                    continue
                # Object identity avoids stale results even when an address changes away and back.
                state = {'kind': 'queued', 'message': 'В очереди', 'url': row['address'], 'elapsed_ms': 0}
                self.states[key] = state
                self.jobs.put((key, row['address'], state))
            return self.snapshot()

    def run(self):
        while not self.closed.is_set():
            try:
                key, address, state = self.jobs.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                with self.lock:
                    if self.states.get(key) is not state:
                        continue
                    state.update(kind='checking', message='Проверяем доступность…')
                try:
                    result = self.checker(address)
                except Exception:
                    result = CheckResult('unreachable', 'Не удалось выполнить проверку.', address)
                with self.lock:
                    if self.states.get(key) is state:
                        self.states[key] = asdict(result)
            finally:
                self.jobs.task_done()
