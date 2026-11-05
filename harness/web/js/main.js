/**
 * main.js - Control Room Application Entry Point
 * Orchestrates Store, API, Renderers, Motion, Palette, and Keyboard interactions.
 */

import { fetchState, postControl, fetchAnswers } from './api.js';
import { store } from './store.js';
import { h } from './dom.js';
import { flipRemove } from './motion.js';
import {
  renderCommandBar,
  renderCycleRing,
  renderHeroStrip,
  renderProgressPanel,
  renderSendQueue,
  renderNeedsYou,
  renderFunnelRibbon,
  renderJobsTable,
  renderLibraryAccordions,
  renderAnswersTable,
  renderUndoBanner,
} from './render.js';
import { initPalette } from './palette.js';
import { initKeys } from './keys.js';

let pollTimerId = null;
let pollIntervalMs = 5000;
let undoTickIntervalId = null;

async function refreshState() {
  try {
    const data = await fetchState();
    if (data !== null) {
      store.setData(data);
    }
    // Success: restore standard 5s polling interval
    pollIntervalMs = 5000;
  } catch (err) {
    console.error('Polling error:', err);
    // Error backoff: 30s
    pollIntervalMs = 30000;
  } finally {
    scheduleNextPoll();
  }
}

function scheduleNextPoll() {
  if (pollTimerId) clearTimeout(pollTimerId);
  if (document.hidden) return; // Paused while tab is hidden
  pollTimerId = setTimeout(refreshState, pollIntervalMs);
}

// 1. Initial State Render Pipeline
function renderAll(data) {
  if (!data) return;
  renderCommandBar(data, store);
  renderCycleRing(data);
  renderProgressPanel(store);
  renderHeroStrip(data, store);
  renderSendQueue(data, store);
  renderNeedsYou(data, store);
  renderFunnelRibbon(data, store);
  renderJobsTable(data, store);
  renderLibraryAccordions(data, store);

  const footerSync = document.getElementById('footer-last-sync');
  if (footerSync) {
    const now = new Date();
    footerSync.textContent = `Updated: ${now.toTimeString().slice(0, 8)} UTC`;
  }
}

// 2. View Switching Handler
function updateViewDOM(viewName) {
  const views = {
    today: document.getElementById('view-today'),
    pipeline: document.getElementById('view-pipeline'),
    library: document.getElementById('view-library'),
    answers: document.getElementById('view-answers'),
  };

  Object.entries(views).forEach(([name, el]) => {
    if (!el) return;
    const isActive = name === viewName;
    el.style.display = isActive ? 'flex' : 'none';
    el.classList.toggle('active', isActive);
  });

  const tabs = document.querySelectorAll('.segmented-control .seg-btn');
  tabs.forEach(tab => {
    const v = tab.getAttribute('data-view');
    const isActive = v === viewName;
    tab.classList.toggle('active', isActive);
    tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
  });

  // Re-render when switching to ensure fresh state
  if (store.data) {
    if (viewName === 'pipeline') {
      renderFunnelRibbon(store.data, store);
      renderJobsTable(store.data, store);
    } else if (viewName === 'library') {
      renderLibraryAccordions(store.data, store);
    } else if (viewName === 'answers') {
      loadAndRenderAnswers();
    } else {
      renderHeroStrip(store.data, store);
      renderSendQueue(store.data, store);
      renderNeedsYou(store.data, store);
    }
  }
}

async function loadAndRenderAnswers() {
  try {
    const data = await fetchAnswers('drafted');
    renderAnswersTable(data.answers || [], handleAnswerAction);
  } catch (err) {
    console.error('Failed to load answers:', err);
  }
}

async function handleAnswerAction(id, action, answer) {
  try {
    const payload = { id, action };
    if (answer !== undefined && answer !== null) {
      payload.answer = answer;
    }
    await postControl('answer', payload);
    await loadAndRenderAnswers();
  } catch (err) {
    alert(`Answer action failed: ${err.message}`);
  }
}

// 3. Contact Decision Handler (SENT or SKIPPED with 6s Undo Window)
function handleMarkContact(contact, status) {
  if (!contact || !contact.id) return;

  const container = document.getElementById('queue-card-list');
  const cardEl = container ? container.querySelector(`.queue-row[data-id="${contact.id}"]`) : null;

  // Collapse row with FLIP animation
  if (cardEl && container) {
    flipRemove(cardEl, container, () => {
      renderHeroStrip(store.data);
    });
  }

  // Clear any existing undo action
  store.clearPendingUndo();
  if (undoTickIntervalId) clearInterval(undoTickIntervalId);

  const expiresAt = Date.now() + 6000;

  const timeoutId = setTimeout(async () => {
    // 6 seconds passed: commit change to server
    try {
      await postControl('mark', { id: contact.id, status });
      store.announce(`Sent outreach mark: ${contact.name} as ${status}`);
    } catch (err) {
      console.error('Failed to commit mark:', err);
      store.announce(`Error: Could not save ${status} for ${contact.name}`);
    } finally {
      store.clearPendingUndo();
      if (undoTickIntervalId) clearInterval(undoTickIntervalId);
      refreshState();
    }
  }, 6000);

  const pendingObj = {
    id: contact.id,
    status,
    contact,
    timeoutId,
    expiresAt,
  };

  store.setPendingUndo(pendingObj);

  // Tick down the button label every 500ms
  undoTickIntervalId = setInterval(() => {
    if (!store.pendingUndo) {
      clearInterval(undoTickIntervalId);
      return;
    }
    renderUndoBanner(store.pendingUndo);
  }, 500);
}

// 4. Setup Hold-to-Confirm Kill Switch (600ms Press)
function setupKillSwitch() {
  const btn = document.getElementById('btn-killswitch');
  const progress = document.getElementById('kill-progress');
  if (!btn || !progress) return;

  let holdTimer = null;
  const HOLD_DURATION = 600;

  function startHold(e) {
    e.preventDefault();
    progress.style.transition = `width ${HOLD_DURATION}ms linear`;
    progress.style.width = '100%';

    holdTimer = setTimeout(async () => {
      progress.style.transition = 'none';
      progress.style.width = '0%';
      holdTimer = null;

      const ksList = store.data?.kill_switch || [];
      const currentOn = Boolean(ksList.length > 0 && ksList[0].on);
      const nextOn = !currentOn;

      try {
        await postControl('kill', { on: nextOn });
        store.announce(nextOn ? 'Kill switch engaged. System halted.' : 'Kill switch released.');
        await refreshState();
      } catch (err) {
        console.error('Kill switch toggle failed:', err);
      }
    }, HOLD_DURATION);
  }

  function cancelHold() {
    if (holdTimer) {
      clearTimeout(holdTimer);
      holdTimer = null;
    }
    progress.style.transition = 'none';
    progress.style.width = '0%';
  }

  btn.addEventListener('pointerdown', startHold);
  btn.addEventListener('pointerup', cancelHold);
  btn.addEventListener('pointerleave', cancelHold);
  btn.addEventListener('pointercancel', cancelHold);
}

// 5. Setup Global UI Event Listeners
function setupUIListeners() {
  // Segmented Control Navigation
  const segmentedControl = document.querySelector('.segmented-control');
  if (segmentedControl) {
    segmentedControl.addEventListener('click', (e) => {
      const btn = e.target.closest('.seg-btn');
      if (!btn) return;
      const targetView = btn.getAttribute('data-view');
      store.setView(targetView);
    });
  }

  // Schedule Dropdown Menu
  const scheduleBtn = document.getElementById('btn-schedule-menu');
  const scheduleDropdown = document.getElementById('schedule-dropdown');
  if (scheduleBtn && scheduleDropdown) {
    scheduleBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      store.setScheduleMenuOpen(!store.scheduleMenuOpen);
    });
  }

  // Close dropdown on outside click
  document.addEventListener('click', (e) => {
    if (store.scheduleMenuOpen && !e.target.closest('.dropdown-wrapper')) {
      store.setScheduleMenuOpen(false);
      resetAutoapplyConfirm();
    }
  });

  // Schedule Toggles
  const schedBtn = document.getElementById('btn-toggle-schedule');
  if (schedBtn) {
    schedBtn.addEventListener('click', async () => {
      const on = !store.data?.settings?.['ctl:schedule'];
      await postControl('toggle', { name: 'schedule', on });
      await refreshState();
    });
  }

  const portalsBtn = document.getElementById('btn-toggle-portals');
  if (portalsBtn) {
    portalsBtn.addEventListener('click', async () => {
      const on = !store.data?.settings?.['ctl:portals'];
      await postControl('toggle', { name: 'portals', on });
      await refreshState();
    });
  }

  const peopleBtn = document.getElementById('btn-toggle-people');
  if (peopleBtn) {
    peopleBtn.addEventListener('click', async () => {
      const on = !store.data?.settings?.['ctl:people'];
      await postControl('toggle', { name: 'people', on });
      await refreshState();
    });
  }

  const submitBtn = document.getElementById('btn-toggle-submit');
  let submitConfirmTimer = null;
  function resetSubmitConfirm() {
    if (submitConfirmTimer) {
      clearTimeout(submitConfirmTimer);
      submitConfirmTimer = null;
    }
    if (submitBtn && submitBtn.dataset.confirming) {
      delete submitBtn.dataset.confirming;
      const cur = Number(store.data?.settings?.['ctl:submit'] || 0);
      submitBtn.textContent = `Submit for real: ${cur ? 'On' : 'Off'}`;
    }
  }

  if (submitBtn) {
    submitBtn.addEventListener('click', async () => {
      const current = Number(store.data?.settings?.['ctl:submit'] || 0);
      if (current === 0) {
        // Off -> On: requires confirmation (second click within 5s)
        if (submitConfirmTimer) {
          resetSubmitConfirm();
          try {
            await postControl('submit', { on: true, confirm: true });
            await refreshState();
            store.announce('Submit for real turned on');
          } catch (err) {
            store.announce(err.message || 'Cannot enable submit');
            await refreshState();
          }
        } else {
          submitBtn.dataset.confirming = 'true';
          submitBtn.textContent = 'Confirm SUBMIT? (click again)';
          submitConfirmTimer = setTimeout(() => {
            resetSubmitConfirm();
          }, 5000);
        }
      } else {
        // On -> Off: immediate, no confirm
        resetSubmitConfirm();
        try {
          await postControl('submit', { on: false });
          await refreshState();
          store.announce('Submit for real turned off');
        } catch (err) {
          store.announce(err.message || 'Failed to turn off submit');
          await refreshState();
        }
      }
    });
  }

  // Persistent Submit Badge Click: One-click immediate path to Off
  const badgeAutoapply = document.getElementById('badge-autoapply');
  if (badgeAutoapply) {
    badgeAutoapply.addEventListener('click', async () => {
      resetSubmitConfirm();
      try {
        await postControl('submit', { on: false });
        await refreshState();
        store.announce('Submit for real turned off');
      } catch (err) {
        console.error('Failed to turn off submit:', err);
      }
    });
  }

  // Theme Toggle Button
  const themeBtn = document.getElementById('btn-theme');
  if (themeBtn) {
    themeBtn.addEventListener('click', () => {
      if (document.startViewTransition) {
        document.startViewTransition(() => store.toggleTheme());
      } else {
        store.toggleTheme();
      }
    });
  }

  // Keyboard Shortcuts Modal Toggle
  const shortcutsBtn = document.getElementById('btn-shortcuts');
  const shortcutsCloseBtn = document.getElementById('btn-close-shortcuts');
  const shortcutsBackdrop = document.getElementById('shortcuts-modal-backdrop');
  const openPaletteFromHelp = document.getElementById('btn-open-palette-from-help');

  if (shortcutsBtn) {
    shortcutsBtn.addEventListener('click', () => {
      store.setActiveModal('shortcuts');
    });
  }
  if (shortcutsCloseBtn) {
    shortcutsCloseBtn.addEventListener('click', () => {
      store.setActiveModal(null);
    });
  }
  if (shortcutsBackdrop) {
    shortcutsBackdrop.addEventListener('click', (e) => {
      if (e.target === shortcutsBackdrop) store.setActiveModal(null);
    });
  }
  if (openPaletteFromHelp) {
    openPaletteFromHelp.addEventListener('click', () => {
      store.setActiveModal('palette');
    });
  }

  // Run Cycle Now Button
  const runNowBtn = document.getElementById('btn-run-now');
  if (runNowBtn) {
    runNowBtn.addEventListener('click', async () => {
      runNowBtn.disabled = true;
      runNowBtn.textContent = 'Starting…';
      let label = 'Run cycle now';
      try {
        const res = await postControl('run_now', {});
        label = res.started ? 'Started ✓' : 'Already running';
        store.announce(res.started ? 'Cycle started' : 'A cycle is already running');
        await refreshState();
      } catch (err) {
        console.error(err);
        label = 'Failed — see log';
        store.announce('Could not start the cycle: ' + err.message);
      } finally {
        runNowBtn.textContent = label;
        setTimeout(() => { runNowBtn.disabled = false; runNowBtn.textContent = 'Run cycle now'; }, 3000);
      }
    });
  }

  // Undo Button in Banner
  const undoBtn = document.getElementById('btn-undo-action');
  if (undoBtn) {
    undoBtn.addEventListener('click', () => {
      if (store.pendingUndo) {
        store.clearPendingUndo();
        if (undoTickIntervalId) clearInterval(undoTickIntervalId);
        store.announce('Decision undone. Contact restored.');
        renderSendQueue(store.data, store);
        renderHeroStrip(store.data, store);
        renderUndoBanner(null);
      }
    });
  }

  // Event Delegation for Send Queue Mark Buttons
  const queueContainer = document.getElementById('queue-card-list');
  if (queueContainer) {
    queueContainer.addEventListener('click', (e) => {
      const btn = e.target.closest('.btn-mark-action');
      if (!btn) return;
      e.stopPropagation();
      const contactId = Number(btn.getAttribute('data-id'));
      const action = btn.getAttribute('data-action');
      const contact = (store.data?.contacts || []).find(c => c.id === contactId);
      if (contact && action) {
        handleMarkContact(contact, action);
      }
    });
  }

  // Jobs Filter Bar Chips
  const filterBar = document.getElementById('jobs-filter-bar');
  if (filterBar) {
    filterBar.addEventListener('click', (e) => {
      const chip = e.target.closest('.filter-chip');
      if (!chip) return;
      const f = chip.getAttribute('data-filter') || '';
      store.setJobsFilter(f);
    });
  }

  // Hero "Needs you" card jumps to the answer inbox
  const heroNeeds = document.getElementById('hero-needs-you');
  if (heroNeeds) {
    const jump = () => document.getElementById('needs-you-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    heroNeeds.addEventListener('click', jump);
    heroNeeds.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); jump(); } });
  }

  // Jobs date chips
  const dateBar = document.getElementById('jobs-date-bar');
  if (dateBar) {
    dateBar.addEventListener('click', (e) => {
      const chip = e.target.closest('.filter-chip');
      if (!chip) return;
      store.setJobsDate(chip.getAttribute('data-date') || '');
    });
  }

  // Apply to pending jobs
  const applyBtn = document.getElementById('btn-apply-now');
  const applyNote = document.getElementById('apply-now-note');
  if (applyBtn) {
    applyBtn.addEventListener('click', async () => {
      applyBtn.disabled = true;
      try {
        const isLive = Number(store.data?.settings?.['ctl:submit'] ?? 0) === 1;
        const res = await postControl('apply_now', {});
        if (applyNote) {
          applyNote.textContent = res.started
            ? (isLive ? 'Live apply started. Watch Today for progress.' : 'Shadow run started: forms are filled but NOT submitted.')
            : (res.reason || 'Could not start.');
        }
      } catch (err) {
        console.error('apply_now failed', err);
        if (applyNote) applyNote.textContent = 'Could not start the apply run.';
      }
      applyBtn.disabled = false;
      refreshState();
    });
  }

  // Jobs Search Input
  const searchInput = document.getElementById('jobs-search');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      store.setJobsSearch(e.target.value);
    });
  }

  // Handle Hash Changes from Browser History
  window.addEventListener('hashchange', () => {
    const hash = window.location.hash.replace('#', '').toLowerCase();
    if (hash === 'pipeline' || hash === 'library' || hash === 'today') {
      store.setView(hash);
    }
  });

  // Handle Tab Visibility (Pause background polling when tab hidden)
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
      refreshState();
    } else {
      if (pollTimerId) clearTimeout(pollTimerId);
    }
  });
}

// 6. Store Event Subscriptions
function setupStoreSubscriptions() {
  store.addEventListener('change:theme', (e) => {
    document.documentElement.setAttribute('data-theme', e.detail.theme);
  });

  store.addEventListener('change:view', (e) => {
    updateViewDOM(e.detail.view);
  });

  store.addEventListener('change:expansion', (e) => {
    const row = document.querySelector(`.queue-row[data-id="${e.detail.id}"]`);
    if (row) {
      row.classList.toggle('expanded', e.detail.expanded);
    }
  });

  store.addEventListener('change:schedule_menu', (e) => {
    const dropdown = document.getElementById('schedule-dropdown');
    const btn = document.getElementById('btn-schedule-menu');
    if (dropdown) dropdown.classList.toggle('active', e.detail.open);
    if (btn) btn.setAttribute('aria-expanded', e.detail.open ? 'true' : 'false');
  });

  store.addEventListener('change:data', (e) => {
    renderAll(e.detail.data);
  });

  store.addEventListener('change:filter', () => {
    const chips = document.querySelectorAll('#jobs-filter-bar .filter-chip');
    chips.forEach(chip => {
      const f = chip.getAttribute('data-filter') || '';
      chip.classList.toggle('active', f === store.jobsFilter);
    });
    document.querySelectorAll('#jobs-date-bar .filter-chip').forEach(chip => {
      chip.classList.toggle('active', (chip.getAttribute('data-date') || '') === store.jobsDate);
    });
    renderJobsTable(store.data, store);
    renderFunnelRibbon(store.data, store);
  });

  store.addEventListener('change:queue', () => {
    const rows = document.querySelectorAll('.queue-row');
    rows.forEach((row, idx) => {
      row.classList.toggle('focused', idx === store.queueIndex);
    });
  });

  store.addEventListener('change:undo', (e) => {
    renderUndoBanner(e.detail.undo);
  });

  store.addEventListener('change:modal', (e) => {
    const isShortcuts = e.detail.modal === 'shortcuts';
    const shortcutsBackdrop = document.getElementById('shortcuts-modal-backdrop');
    if (shortcutsBackdrop) {
      shortcutsBackdrop.classList.toggle('active', isShortcuts);
      shortcutsBackdrop.setAttribute('aria-hidden', isShortcuts ? 'false' : 'true');
    }
  });
}

// 7. Application Boot
function boot() {
  document.documentElement.setAttribute('data-theme', store.theme);

  setupUIListeners();
  setupKillSwitch();
  setupStoreSubscriptions();
  initPalette(store);
  initKeys(store, handleMarkContact);

  // Apply initial view from hash or default
  updateViewDOM(store.currentView);

  // Initial data fetch
  refreshState();
  refreshDecisions();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}
