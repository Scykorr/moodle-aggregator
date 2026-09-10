'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const labels = {
  idle: 'Не проверен', queued: 'В очереди', checking: 'Проверяем…', moodle: 'Moodle обнаружен',
  unknown: 'Moodle не подтверждён', restricted: 'Доступ ограничен', unreachable: 'Нет соединения',
  invalid: 'Ошибка адреса', http_error: 'Ошибка HTTP',
};

let token = '';
let revision = 0;
let title = 'Учебные площадки';
let faculties = [];
let items = [];
let dirty = false;
let working = false;
let authorized = false;
let polling = false;
let dragPayload = null;

function notify(text, error = false) {
  $('#notice').textContent = text;
  $('#notice').classList.toggle('error', error);
}

function setDirty(value) {
  dirty = value;
  $('#save-state').textContent = value ? 'Есть несохранённые изменения' : 'Все изменения сохранены';
  $('#save-state').classList.toggle('dirty', value);
}

function newId(prefix) {
  const raw = globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}-${raw}`.slice(0, 64);
}

async function api(path, method = 'GET', body) {
  const headers = { 'X-Aggregator-Request': '1' };
  if (token) headers.Authorization = 'Bearer ' + token;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: 'no-store',
  });
  const data = await response.json();
  if (response.status === 401) {
    authorized = false;
    $('#login').hidden = false;
    $('#workspace').hidden = true;
  }
  if (!response.ok) throw new Error(data.error || 'Ошибка соединения с агрегатором.');
  return data;
}

function itemById(id) {
  return items.find((item) => item.id === id);
}

function orphans() {
  return items.filter((item) => !item.faculty_id);
}

function updateItemStatus(element, item) {
  const kind = item.kind || 'idle';
  const badge = element.querySelector('.badge');
  badge.className = 'badge ' + kind;
  badge.textContent = labels[kind] || 'Не проверен';
  element.querySelector('.result-detail').textContent = kind === 'idle' ? '' : (item.message || '');
  const checkBtn = element.querySelector('.check-item');
  checkBtn.disabled = working || !item.address || ['queued', 'checking'].includes(kind);
}

function bindItemCard(element, item) {
  element.dataset.id = item.id;
  const nameInput = element.querySelector('.item-name');
  const addressInput = element.querySelector('.item-address');
  nameInput.value = item.name || '';
  addressInput.value = item.address || '';
  nameInput.addEventListener('input', () => { item.name = nameInput.value; setDirty(true); });
  addressInput.addEventListener('input', () => {
    item.address = addressInput.value;
    item.kind = 'idle';
    item.message = '';
    setDirty(true);
    updateItemStatus(element, item);
  });
  element.querySelector('.check-item').addEventListener('click', () => runCheck([item.id]));
  element.querySelector('.remove-item').addEventListener('click', () => {
    items = items.filter((row) => row.id !== item.id);
    faculties.forEach((faculty) => {
      faculty.children = faculty.children.filter((id) => id !== item.id);
    });
    setDirty(true);
    render();
  });

  element.addEventListener('dragstart', (event) => {
    dragPayload = { type: 'item', id: item.id };
    element.classList.add('dragging');
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', item.id);
  });
  element.addEventListener('dragend', () => {
    element.classList.remove('dragging');
    dragPayload = null;
    clearDragOver();
  });

  updateItemStatus(element, item);
}

function clearDragOver() {
  document.querySelectorAll('.drag-over').forEach((node) => node.classList.remove('drag-over'));
}

function makeItemCard(item) {
  const element = $('#item-template').content.firstElementChild.cloneNode(true);
  bindItemCard(element, item);
  return element;
}

function moveItem(itemId, facultyId, beforeId) {
  const item = itemById(itemId);
  if (!item) return;
  const targetFaculty = facultyId || null;
  faculties.forEach((faculty) => {
    faculty.children = faculty.children.filter((id) => id !== itemId);
  });
  item.faculty_id = targetFaculty;
  if (targetFaculty) {
    const faculty = faculties.find((row) => row.id === targetFaculty);
    if (!faculty) return;
    const next = faculty.children.filter((id) => id !== itemId);
    if (beforeId && next.includes(beforeId)) {
      next.splice(next.indexOf(beforeId), 0, itemId);
    } else {
      next.push(itemId);
    }
    faculty.children = next;
  } else if (beforeId) {
    const order = orphans().map((row) => row.id).filter((id) => id !== itemId);
    const idx = order.indexOf(beforeId);
    const arranged = [...order];
    if (idx >= 0) arranged.splice(idx, 0, itemId);
    else arranged.push(itemId);
    const byId = Object.fromEntries(items.map((row) => [row.id, row]));
    const rest = items.filter((row) => row.faculty_id);
    items = [...rest, ...arranged.map((id) => byId[id]).filter(Boolean)];
  }
  setDirty(true);
  render();
}

function reorderFaculty(facultyId, beforeId) {
  const current = faculties.map((row) => row.id).filter((id) => id !== facultyId);
  if (beforeId && current.includes(beforeId)) {
    current.splice(current.indexOf(beforeId), 0, facultyId);
  } else {
    current.push(facultyId);
  }
  const byId = Object.fromEntries(faculties.map((row) => [row.id, row]));
  faculties = current.map((id) => byId[id]).filter(Boolean);
  setDirty(true);
  render();
}

function setupDropList(list, facultyId) {
  list.ondragover = (event) => {
    if (!dragPayload || dragPayload.type !== 'item') return;
    event.preventDefault();
    list.classList.add('drag-over');
  };
  list.ondragleave = () => list.classList.remove('drag-over');
  list.ondrop = (event) => {
    event.preventDefault();
    clearDragOver();
    if (!dragPayload || dragPayload.type !== 'item') return;
    const overCard = event.target.closest('.item-card');
    moveItem(dragPayload.id, facultyId || null, overCard?.dataset.id || null);
  };
}

function bindFacultyCard(element, faculty) {
  element.dataset.id = faculty.id;
  const nameInput = element.querySelector('.faculty-name');
  const descInput = element.querySelector('.faculty-desc');
  nameInput.value = faculty.name || '';
  descInput.value = faculty.description || '';
  nameInput.addEventListener('input', () => { faculty.name = nameInput.value; setDirty(true); });
  descInput.addEventListener('input', () => { faculty.description = descInput.value; setDirty(true); });
  element.querySelector('.remove-faculty').addEventListener('click', () => {
    const childIds = new Set(faculty.children);
    items.forEach((item) => {
      if (childIds.has(item.id) || item.faculty_id === faculty.id) item.faculty_id = null;
    });
    faculties = faculties.filter((row) => row.id !== faculty.id);
    setDirty(true);
    render();
  });

  const list = element.querySelector('.faculty-children');
  faculty.children.forEach((id) => {
    const item = itemById(id);
    if (item) list.append(makeItemCard(item));
  });
  setupDropList(list, faculty.id);

  element.addEventListener('dragstart', (event) => {
    if (event.target.closest('.item-card')) return;
    dragPayload = { type: 'faculty', id: faculty.id };
    element.classList.add('dragging');
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', faculty.id);
  });
  element.addEventListener('dragend', () => {
    element.classList.remove('dragging');
    dragPayload = null;
    clearDragOver();
  });
  element.addEventListener('dragover', (event) => {
    if (!dragPayload || dragPayload.type !== 'faculty') return;
    event.preventDefault();
    element.classList.add('drag-over');
  });
  element.addEventListener('dragleave', () => element.classList.remove('drag-over'));
  element.addEventListener('drop', (event) => {
    if (!dragPayload || dragPayload.type !== 'faculty') return;
    event.preventDefault();
    clearDragOver();
    if (dragPayload.id === faculty.id) return;
    reorderFaculty(dragPayload.id, faculty.id);
  });
}

function render() {
  const facultyRoot = $('#faculties');
  const orphanRoot = $('#orphans');
  facultyRoot.replaceChildren();
  orphanRoot.replaceChildren();

  faculties.forEach((faculty) => {
    const element = $('#faculty-template').content.firstElementChild.cloneNode(true);
    bindFacultyCard(element, faculty);
    facultyRoot.append(element);
  });
  $('#faculties-empty').hidden = faculties.length > 0;

  orphans().forEach((item) => orphanRoot.append(makeItemCard(item)));
  setupDropList(orphanRoot, '');
}

function apply(data) {
  revision = data.revision;
  title = data.title || 'Учебные площадки';
  faculties = (data.faculties || []).map((faculty) => ({
    id: faculty.id,
    name: faculty.name || '',
    description: faculty.description || '',
    children: Array.isArray(faculty.children) ? [...faculty.children] : [],
  }));
  items = (data.items || []).map((item) => ({
    id: item.id,
    name: item.name || '',
    address: item.address || '',
    faculty_id: item.faculty_id || null,
    kind: item.kind || 'idle',
    message: item.message || '',
    url: item.url || '',
    elapsed_ms: item.elapsed_ms || 0,
  }));
  $('#catalog-title').value = title;
  setDirty(false);
  render();
}

function payload() {
  // Rebuild children from current faculty membership + order in UI arrays.
  const nextFaculties = faculties.map((faculty) => ({
    id: faculty.id,
    name: faculty.name,
    description: faculty.description || '',
    children: items.filter((item) => item.faculty_id === faculty.id).map((item) => item.id),
  }));
  // Preserve explicit children order when still valid.
  nextFaculties.forEach((faculty, index) => {
    const preferred = faculties[index]?.children || [];
    const set = new Set(faculty.children);
    const ordered = preferred.filter((id) => set.has(id));
    faculty.children.forEach((id) => {
      if (!ordered.includes(id)) ordered.push(id);
    });
    faculty.children = ordered;
  });
  return {
    revision,
    title,
    faculties: nextFaculties,
    items: items.map(({ id, name, address, faculty_id }) => ({ id, name, address, faculty_id })),
  };
}

async function save() {
  const data = await api('/api/catalog', 'PUT', payload());
  apply(data);
  return data;
}

async function action(fn) {
  if (working) return;
  working = true;
  notify('');
  try {
    await fn();
  } catch (error) {
    notify(error.message, true);
  } finally {
    working = false;
    render();
  }
}

async function runCheck(ids) {
  const usable = ids.filter((id) => {
    const item = itemById(id);
    return item && item.address.trim();
  });
  if (!usable.length) {
    notify('Нет площадок с адресом для проверки.', true);
    return;
  }
  await action(async () => {
    await save();
    const data = await api('/api/check', 'POST', { ids: usable });
    const byId = Object.fromEntries((data.servers || []).map((row) => [row.id, row]));
    items.forEach((item) => {
      const row = byId[item.id];
      if (row) Object.assign(item, row);
    });
    notify('Проверки запущены. Результаты обновляются автоматически.');
  });
}

$('#catalog-title').addEventListener('input', (event) => {
  title = event.target.value;
  setDirty(true);
});

$('#add-faculty').addEventListener('click', () => {
  faculties.push({ id: newId('fac'), name: 'Новый факультет', description: '', children: [] });
  setDirty(true);
  render();
});

$('#add-item').addEventListener('click', () => {
  items.push({
    id: newId('dep'),
    name: 'Новая кафедра',
    address: '',
    faculty_id: null,
    kind: 'idle',
    message: '',
  });
  setDirty(true);
  render();
});

$('#save').addEventListener('click', () => action(async () => {
  await save();
  notify('Каталог сохранён.');
}));

$('#check-all').addEventListener('click', () => {
  runCheck(items.map((item) => item.id));
});

async function load() {
  const data = await api('/api/catalog?admin=1');
  authorized = true;
  $('#login').hidden = true;
  $('#workspace').hidden = false;
  apply(data);
  notify('');
}

$('#login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  token = $('#password').value;
  try {
    await load();
    $('#password').value = '';
  } catch (error) {
    notify(error.message, true);
  }
});

async function poll() {
  if (!authorized || working || polling || dirty) return;
  polling = true;
  try {
    const data = await api('/api/catalog?admin=1');
    if (data.revision !== revision) {
      apply(data);
      return;
    }
    const byId = Object.fromEntries((data.items || []).map((row) => [row.id, row]));
    items.forEach((item) => {
      const incoming = byId[item.id];
      if (incoming && incoming.address === item.address) {
        item.kind = incoming.kind;
        item.message = incoming.message;
        item.url = incoming.url;
        item.elapsed_ms = incoming.elapsed_ms;
      }
    });
    document.querySelectorAll('.item-card').forEach((element) => {
      const item = itemById(element.dataset.id);
      if (item) updateItemStatus(element, item);
    });
  } catch (error) {
    notify(error.message, true);
  } finally {
    polling = false;
  }
}

load().catch((error) => notify(error.message, true));
setInterval(poll, 1200);
window.addEventListener('beforeunload', (event) => {
  if (dirty) {
    event.preventDefault();
    event.returnValue = '';
  }
});
