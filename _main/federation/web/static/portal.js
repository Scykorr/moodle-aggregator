'use strict';

const OTHER_ID = '__other__';

function $(sel, root = document) { return root.querySelector(sel); }

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function itemsForFaculty(items, facultyId) {
  if (facultyId === OTHER_ID) {
    return items.filter((item) => !item.faculty_id);
  }
  return items.filter((item) => item.faculty_id === facultyId);
}

function renderCards(items) {
  if (!items.length) {
    return '<p class="empty">В этом разделе пока нет площадок.</p>';
  }
  return `<div class="grid">${items.map((item) => {
    const hasLink = Boolean(item.address);
    const meta = hasLink ? escapeHtml(item.address) : 'Ссылка не задана';
    const cta = hasLink ? 'Открыть площадку →' : 'Нет адреса';
    if (!hasLink) {
      return `<div class="card disabled"><div class="card-name">${escapeHtml(item.name)}</div><div class="card-meta">${meta}</div><div class="card-cta">${cta}</div></div>`;
    }
    return `<a class="card" href="${escapeHtml(item.address)}" target="_blank" rel="noopener noreferrer"><div class="card-name">${escapeHtml(item.name)}</div><div class="card-meta">${meta}</div><div class="card-cta">${cta}</div></a>`;
  }).join('')}</div>`;
}

function activate(tabId) {
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.setAttribute('aria-selected', tab.dataset.id === tabId ? 'true' : 'false');
  });
  document.querySelectorAll('.panel').forEach((panel) => {
    panel.classList.toggle('active', panel.dataset.id === tabId);
  });
}

async function load() {
  const response = await fetch('/api/catalog', { cache: 'no-store' });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || 'Не удалось загрузить каталог.');
  }

  $('#catalog-title').textContent = data.title || 'Учебные площадки';
  document.title = data.title || 'Учебные площадки';

  const tabs = $('#tabs');
  const panels = $('#panels');
  const empty = $('#empty');
  tabs.replaceChildren();
  panels.replaceChildren();

  const faculties = Array.isArray(data.faculties) ? data.faculties : [];
  const items = Array.isArray(data.items) ? data.items : [];
  const orphanCount = items.filter((item) => !item.faculty_id).length;
  const sections = faculties.map((f) => ({ id: f.id, name: f.name, description: f.description || '' }));
  if (orphanCount || !sections.length) {
    sections.push({ id: OTHER_ID, name: 'Другие площадки', description: 'Площадки вне факультетов.' });
  }

  if (!items.length && !faculties.length) {
    empty.hidden = false;
    return;
  }
  empty.hidden = true;

  sections.forEach((section, index) => {
    const tab = document.createElement('button');
    tab.type = 'button';
    tab.className = 'tab';
    tab.role = 'tab';
    tab.dataset.id = section.id;
    tab.id = `tab-${section.id}`;
    tab.setAttribute('aria-controls', `panel-${section.id}`);
    tab.setAttribute('aria-selected', index === 0 ? 'true' : 'false');
    tab.textContent = section.name;
    tab.addEventListener('click', () => activate(section.id));
    tabs.append(tab);

    const panel = document.createElement('div');
    panel.className = 'panel' + (index === 0 ? ' active' : '');
    panel.dataset.id = section.id;
    panel.id = `panel-${section.id}`;
    panel.role = 'tabpanel';
    panel.setAttribute('aria-labelledby', `tab-${section.id}`);
    const intro = section.description
      ? `<p class="panel-intro">${escapeHtml(section.description)}</p>`
      : '';
    panel.innerHTML = intro + renderCards(itemsForFaculty(items, section.id));
    panels.append(panel);
  });
}

load().catch((error) => {
  const empty = $('#empty');
  empty.hidden = false;
  empty.textContent = error.message;
});
