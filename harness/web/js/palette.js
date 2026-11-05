/**
 * palette.js - Command Palette (⌘K / Ctrl+K)
 * Fast client-side fuzzy command search and navigation across Today, Pipeline, Library.
 */

import { postControl } from './api.js';

export function initPalette(store) {
  const backdrop = document.getElementById('command-palette-backdrop');
  const input = document.getElementById('palette-input');
  const results = document.getElementById('palette-results');
  if (!backdrop || !input || !results) return;

  let selectedIdx = 0;
  let currentCommands = [];

  function openAndScroll(viewName, elementId, accordionId) {
    store.setView(viewName);
    if (accordionId) {
      const acc = document.getElementById(accordionId);
      if (acc) acc.open = true;
    }
    setTimeout(() => {
      const el = document.getElementById(elementId);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 50);
  }

  const COMMANDS = [
    { title: 'View: Today', desc: 'Open primary workspace with Send Queue and Blockers', action: () => store.setView('today') },
    { title: 'View: Pipeline', desc: 'Open Target Jobs table and funnel bar', action: () => store.setView('pipeline') },
    { title: 'View: Library', desc: 'Open archives: Contacts, Drafts, Answers, and Runs', action: () => store.setView('library') },
    { title: 'Jump to: Send Queue', desc: 'Active contact cards awaiting outreach', action: () => openAndScroll('today', 'send-queue-panel') },
    { title: 'Jump to: Needs You', desc: 'Blocked jobs needing user action', action: () => openAndScroll('today', 'needs-you-panel') },
    { title: 'Jump to: Target Jobs', desc: 'Sortable and searchable jobs database', action: () => openAndScroll('pipeline', 'jobs-section') },
    { title: 'Jump to: All Contacts', desc: 'Full scored networking contacts table', action: () => openAndScroll('library', 'acc-contacts', 'acc-contacts') },
    { title: 'Jump to: Queued Messages', desc: 'LinkedIn drafts pending mobile review', action: () => openAndScroll('library', 'acc-queued', 'acc-queued') },
    { title: 'Jump to: Recruiter Drafts', desc: 'Email drafts and outreach letters', action: () => openAndScroll('library', 'acc-drafts', 'acc-drafts') },
    { title: 'Jump to: Application Answers', desc: 'Saved story answers with reveal button', action: () => openAndScroll('library', 'acc-app-answers', 'acc-app-answers') },
    { title: 'Jump to: Screening Answers', desc: 'Screening QA keys with reveal button', action: () => openAndScroll('library', 'acc-screening', 'acc-screening') },
    { title: 'Jump to: Run History', desc: 'Timeline of cycles and automation runs', action: () => openAndScroll('library', 'acc-runs', 'acc-runs') },
    { title: 'Filter Jobs: To Apply', desc: 'Show only jobs ready for application', action: () => { store.setView('pipeline'); store.setJobsFilter('TO_APPLY'); } },
    { title: 'Filter Jobs: Needs You', desc: 'Show jobs with blocker notes', action: () => { store.setView('pipeline'); store.setJobsFilter('BLOCKED_USER'); } },
    { title: 'Filter Jobs: Applied', desc: 'Show verified submitted jobs', action: () => { store.setView('pipeline'); store.setJobsFilter('APPLIED'); } },
    { title: 'Filter Jobs: Clear Filters', desc: 'Show all jobs', action: () => { store.setView('pipeline'); store.setJobsFilter(''); } },
    { title: 'Action: Run Cycle Now', desc: 'Trigger full 6-hourly cycle immediately', action: async () => { await postControl('run_now', {}); store.announce('Cycle triggered'); } },
    { title: 'Action: Toggle Schedule', desc: 'Toggle automated 6-hourly runner', action: async () => { const on = !store.data?.settings?.['ctl:schedule']; await postControl('toggle', { name: 'schedule', on }); } },
    { title: 'Action: Toggle Portals Phase', desc: 'Enable/disable India portals phase (Naukri, Instahyre)', action: async () => { const on = !store.data?.settings?.['ctl:portals']; await postControl('toggle', { name: 'portals', on }); } },
    { title: 'Action: Toggle People Phase', desc: 'Enable/disable contact networking phase', action: async () => { const on = !store.data?.settings?.['ctl:people']; await postControl('toggle', { name: 'people', on }); } },
    { title: 'Action: Toggle Submit for Real', desc: 'Enable/disable live application submission', action: async () => {
      const cur = Number(store.data?.settings?.['ctl:submit'] || 0);
      const next = !cur;
      if (next && typeof window !== 'undefined' && window.confirm && !window.confirm('Enable real application submissions?')) return;
      await postControl('submit', { on: next, confirm: next });
      if (store.data?.settings) store.data.settings['ctl:submit'] = next ? 1 : 0;
      store.announce(`Submit for real turned ${next ? 'on' : 'off'}`);
    } },
    { title: 'Action: Toggle Theme', desc: 'Switch between dark graphite and light paper theme', action: () => store.toggleTheme() },
    { title: 'Help: Keyboard Shortcuts', desc: 'Open full keyboard shortcuts guide', action: () => store.setActiveModal('shortcuts') },
  ];

  function filterCommands(query) {
    const q = (query || '').toLowerCase().trim();
    if (!q) return COMMANDS;
    return COMMANDS.filter(c => c.title.toLowerCase().includes(q) || c.desc.toLowerCase().includes(q));
  }

  function renderList() {
    results.replaceChildren();
    if (currentCommands.length === 0) {
      const empty = document.createElement('li');
      empty.className = 'palette-item';
      empty.textContent = 'No matching commands found';
      results.appendChild(empty);
      return;
    }

    currentCommands.forEach((cmd, idx) => {
      const li = document.createElement('li');
      li.className = `palette-item ${idx === selectedIdx ? 'selected' : ''}`;
      li.setAttribute('role', 'option');
      li.setAttribute('aria-selected', idx === selectedIdx ? 'true' : 'false');

      const title = document.createElement('div');
      title.className = 'palette-item-title';
      title.textContent = cmd.title;

      const desc = document.createElement('div');
      desc.className = 'palette-item-desc';
      desc.textContent = cmd.desc;

      li.appendChild(title);
      li.appendChild(desc);

      li.addEventListener('click', () => {
        execute(cmd);
      });

      results.appendChild(li);
    });

    const activeEl = results.children[selectedIdx];
    if (activeEl && typeof activeEl.scrollIntoView === 'function') {
      activeEl.scrollIntoView({ block: 'nearest' });
    }
  }

  function execute(cmd) {
    store.setActiveModal(null);
    if (cmd && typeof cmd.action === 'function') {
      cmd.action();
    }
  }

  input.addEventListener('input', () => {
    selectedIdx = 0;
    currentCommands = filterCommands(input.value);
    renderList();
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      selectedIdx = (selectedIdx + 1) % Math.max(1, currentCommands.length);
      renderList();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      selectedIdx = (selectedIdx - 1 + currentCommands.length) % Math.max(1, currentCommands.length);
      renderList();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (currentCommands[selectedIdx]) {
        execute(currentCommands[selectedIdx]);
      }
    } else if (e.key === 'Escape') {
      e.preventDefault();
      store.setActiveModal(null);
    }
  });

  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop) {
      store.setActiveModal(null);
    }
  });

  // Modal open / close subscriber
  store.addEventListener('change:modal', (e) => {
    const isPalette = e.detail.modal === 'palette';
    backdrop.classList.toggle('active', isPalette);
    backdrop.setAttribute('aria-hidden', isPalette ? 'false' : 'true');

    if (isPalette) {
      input.value = '';
      selectedIdx = 0;
      currentCommands = COMMANDS;
      renderList();
      setTimeout(() => input.focus(), 50);
    }
  });
}
