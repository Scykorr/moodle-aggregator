"""Hierarchical Moodle catalog: faculties and standalone departments."""
import json
import re
import threading
from pathlib import Path

from moodle_check import normalize_address
from registry import ConflictError

ID_RE = re.compile(r'[a-zA-Z0-9-]{1,64}\Z')


def empty_catalog():
    return {'format': 1, 'revision': 0, 'title': 'Учебные площадки', 'faculties': [], 'items': []}


def validate_catalog(data):
    if not isinstance(data, dict):
        raise ValueError('Ожидается объект каталога.')
    title = data.get('title', 'Учебные площадки')
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise ValueError('Название каталога должно быть непустой строкой до 200 символов.')
    faculties_in = data.get('faculties')
    items_in = data.get('items')
    if not isinstance(faculties_in, list) or not isinstance(items_in, list):
        raise ValueError('faculties и items должны быть списками.')

    faculty_ids = set()
    faculties = []
    for faculty in faculties_in:
        if not isinstance(faculty, dict):
            raise ValueError('Некорректный факультет.')
        key = faculty.get('id')
        name = faculty.get('name')
        description = faculty.get('description', '')
        children = faculty.get('children', [])
        if not isinstance(key, str) or not ID_RE.fullmatch(key) or key in faculty_ids:
            raise ValueError('Идентификаторы факультетов должны быть уникальными.')
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise ValueError('Название факультета обязательно (до 200 символов).')
        if not isinstance(description, str) or len(description) > 1000:
            raise ValueError('Описание факультета — строка до 1000 символов.')
        if not isinstance(children, list) or not all(isinstance(c, str) for c in children):
            raise ValueError('children факультета — список идентификаторов.')
        faculty_ids.add(key)
        faculties.append({
            'id': key,
            'name': name.strip(),
            'description': description.strip(),
            'children': list(children),
        })

    item_ids = set()
    items = []
    for item in items_in:
        if not isinstance(item, dict):
            raise ValueError('Некорректная кафедра/площадка.')
        key = item.get('id')
        name = item.get('name')
        address = item.get('address', '')
        faculty_id = item.get('faculty_id', None)
        if not isinstance(key, str) or not ID_RE.fullmatch(key) or key in item_ids or key in faculty_ids:
            raise ValueError('Идентификаторы кафедр должны быть уникальными.')
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise ValueError('Название кафедры обязательно (до 200 символов).')
        if not isinstance(address, str) or len(address) > 2048:
            raise ValueError('Адрес должен быть строкой до 2048 символов.')
        address = normalize_address(address) if address.strip() else ''
        if faculty_id is not None:
            if not isinstance(faculty_id, str) or faculty_id not in faculty_ids:
                raise ValueError('Кафедра ссылается на неизвестный факультет.')
        item_ids.add(key)
        items.append({
            'id': key,
            'name': name.strip(),
            'address': address,
            'faculty_id': faculty_id,
        })

    by_id = {item['id']: item for item in items}
    seen_in_faculty = set()
    for faculty in faculties:
        ordered = []
        for child_id in faculty['children']:
            item = by_id.get(child_id)
            if item is None:
                continue
            if item['faculty_id'] != faculty['id']:
                continue
            if child_id in seen_in_faculty:
                continue
            ordered.append(child_id)
            seen_in_faculty.add(child_id)
        for item in items:
            if item['faculty_id'] == faculty['id'] and item['id'] not in seen_in_faculty:
                ordered.append(item['id'])
                seen_in_faculty.add(item['id'])
        faculty['children'] = ordered

    for item in items:
        if item['faculty_id'] is not None and item['id'] not in seen_in_faculty:
            item['faculty_id'] = None

    return {
        'format': 1,
        'title': title.strip(),
        'faculties': faculties,
        'items': items,
    }


def migrate_from_servers(servers_path):
    catalog = empty_catalog()
    if not servers_path.exists():
        return catalog
    data = json.loads(servers_path.read_text(encoding='utf-8'))
    if data.get('format') != 1 or not isinstance(data.get('servers'), list):
        return catalog
    items = []
    for row in data['servers']:
        if not isinstance(row, dict):
            continue
        key, address = row.get('id'), row.get('address', '')
        if not isinstance(key, str) or not ID_RE.fullmatch(key):
            continue
        if not isinstance(address, str):
            address = ''
        try:
            address = normalize_address(address) if address.strip() else ''
        except ValueError:
            address = ''
        name = address.rstrip('/') if address else key
        items.append({'id': key, 'name': name, 'address': address, 'faculty_id': None})
    catalog['items'] = items
    return catalog


class Catalog:
    def __init__(self, directory, registry=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'catalog.json'
        self.servers_path = self.directory / 'servers.json'
        self.registry = registry
        self.lock = threading.RLock()
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding='utf-8'))
            if raw.get('format') != 1:
                raise ValueError('Unsupported catalog format')
            validated = validate_catalog(raw)
            self.revision = int(raw.get('revision', 0))
            self.title = validated['title']
            self.faculties = validated['faculties']
            self.items = validated['items']
        else:
            migrated = migrate_from_servers(self.servers_path)
            validated = validate_catalog(migrated)
            self.revision = 0
            self.title = validated['title']
            self.faculties = validated['faculties']
            self.items = validated['items']
            if self.items:
                self._write_unlocked(validated, revision=0)
                self._sync_registry_unlocked()

    def snapshot(self, include_states=False):
        with self.lock:
            items = [dict(item) for item in self.items]
            if include_states and self.registry is not None:
                states = self.registry.snapshot()
                by_id = {row['id']: row for row in states['servers']}
                for item in items:
                    state = by_id.get(item['id'])
                    if state:
                        item['kind'] = state.get('kind', 'idle')
                        item['message'] = state.get('message', '')
                        item['url'] = state.get('url', '')
                        item['elapsed_ms'] = state.get('elapsed_ms', 0)
                    else:
                        item['kind'] = 'idle'
                        item['message'] = 'Не проверен'
                        item['url'] = ''
                        item['elapsed_ms'] = 0
            return {
                'format': 1,
                'revision': self.revision,
                'title': self.title,
                'faculties': [dict(f) for f in self.faculties],
                'items': items,
            }

    def public_snapshot(self):
        return self.snapshot(include_states=False)

    def replace(self, payload, revision):
        validated = validate_catalog(payload)
        with self.lock:
            if revision != self.revision:
                raise ConflictError('Каталог изменён в другом окне. Перезагрузите страницу перед сохранением.')
            if (validated['title'] == self.title
                    and validated['faculties'] == self.faculties
                    and validated['items'] == self.items):
                return self.snapshot(include_states=True)
            self._write_unlocked(validated, revision=self.revision + 1)
            self.title = validated['title']
            self.faculties = validated['faculties']
            self.items = validated['items']
            self.revision += 1
            self._sync_registry_unlocked()
            return self.snapshot(include_states=True)

    def _write_unlocked(self, validated, revision):
        data = {
            'format': 1,
            'revision': revision,
            'title': validated['title'],
            'faculties': validated['faculties'],
            'items': validated['items'],
        }
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temporary.replace(self.path)

    def _sync_registry_unlocked(self):
        if self.registry is None:
            return
        rows = [{'id': item['id'], 'address': item['address']}
                for item in self.items if item['address']]
        self.registry.replace(rows, self.registry.revision)
