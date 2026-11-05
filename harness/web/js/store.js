/**
 * store.js - Central State Container
 * Plain object + EventTarget. Zero external frameworks.
 */

const EXECUTIVE_KEYWORDS = [
  'vp', 'vice president', 'cto', 'ceo', 'coo', 'chief', 'president',
  'founder', 'co-founder', 'director', 'head of', 'general manager',
  'engineering leader', 'tech leader',
];

class Store extends EventTarget {
  constructor() {
    super();
    this.data = null;
    this.currentView = this._initView();
    this.expandedContactIds = new Set();
    this.jobsFilter = '';
    this.jobsSearch = '';
    this.jobsDate = '';
    this.queueIndex = 0;
    this.pendingUndo = null; // { id, status, contact, timeoutId, expiresAt }
    this.activeModal = null; // null | 'palette' | 'shortcuts'
    this.scheduleMenuOpen = false;
    this.theme = this._initTheme();
  }

  _initView() {
    if (typeof window === 'undefined') return 'today';
    const hash = (window.location?.hash || '').replace('#', '').toLowerCase();
    if (hash === 'pipeline' || hash === 'library') return hash;
    return 'today';
  }

  _initTheme() {
    try {
      if (typeof localStorage !== 'undefined') {
        const saved = localStorage.getItem('harness-theme');
        if (saved === 'light' || saved === 'dark') return saved;
      }
    } catch (_) {}
    return typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches
      ? 'light'
      : 'dark';
  }

  setView(viewName) {
    if (viewName !== 'today' && viewName !== 'pipeline' && viewName !== 'library') return;
    this.currentView = viewName;
    try {
      if (typeof window !== 'undefined' && window.location) {
        window.location.hash = viewName;
      }
    } catch (_) {}
    this.dispatchEvent(new CustomEvent('change:view', { detail: { view: this.currentView } }));
  }

  toggleCardExpansion(contactId) {
    const id = Number(contactId);
    if (this.expandedContactIds.has(id)) {
      this.expandedContactIds.delete(id);
    } else {
      this.expandedContactIds.add(id);
    }
    this.dispatchEvent(new CustomEvent('change:expansion', { detail: { id, expanded: this.expandedContactIds.has(id) } }));
  }

  isSenior(contact) {
    const title = (contact?.title || '').toLowerCase();
    return EXECUTIVE_KEYWORDS.some(k => title.includes(k));
  }

  toggleTheme() {
    this.theme = this.theme === 'dark' ? 'light' : 'dark';
    try {
      if (typeof localStorage !== 'undefined') {
        localStorage.setItem('harness-theme', this.theme);
      }
    } catch (_) {}
    this.dispatchEvent(new CustomEvent('change:theme', { detail: { theme: this.theme } }));
  }

  setData(data) {
    this.data = data;
    this.dispatchEvent(new CustomEvent('change:data', { detail: { data } }));
  }

  setJobsFilter(filter) {
    this.jobsFilter = filter;
    this.dispatchEvent(new CustomEvent('change:filter', { detail: { filter: this.jobsFilter, search: this.jobsSearch } }));
  }

  setJobsDate(date) {
    this.jobsDate = date;
    this.dispatchEvent(new CustomEvent('change:filter', { detail: { filter: this.jobsFilter, search: this.jobsSearch } }));
  }

  setJobsSearch(search) {
    this.jobsSearch = search.toLowerCase().trim();
    this.dispatchEvent(new CustomEvent('change:filter', { detail: { filter: this.jobsFilter, search: this.jobsSearch } }));
  }

  setQueueIndex(index) {
    const queue = this.getSendQueue();
    if (queue.length === 0) {
      this.queueIndex = 0;
    } else {
      this.queueIndex = Math.max(0, Math.min(index, queue.length - 1));
    }
    this.dispatchEvent(new CustomEvent('change:queue', { detail: { index: this.queueIndex } }));
  }

  getSendQueue() {
    if (!this.data || !Array.isArray(this.data.contacts)) return [];
    // PREFILLED contacts awaiting send, minus any contact currently in the 6s undo delay
    const pendingId = this.pendingUndo ? this.pendingUndo.id : null;
    return this.data.contacts.filter(c => c.status === 'PREFILLED' && c.id !== pendingId);
  }

  setPendingUndo(undoObj) {
    if (this.pendingUndo && this.pendingUndo.timeoutId) {
      clearTimeout(this.pendingUndo.timeoutId);
    }
    this.pendingUndo = undoObj;
    this.dispatchEvent(new CustomEvent('change:undo', { detail: { undo: this.pendingUndo } }));
  }

  clearPendingUndo() {
    if (this.pendingUndo && this.pendingUndo.timeoutId) {
      clearTimeout(this.pendingUndo.timeoutId);
    }
    this.pendingUndo = null;
    this.dispatchEvent(new CustomEvent('change:undo', { detail: { undo: null } }));
  }

  setActiveModal(modalName) {
    this.activeModal = modalName;
    this.dispatchEvent(new CustomEvent('change:modal', { detail: { modal: modalName } }));
  }

  setScheduleMenuOpen(isOpen) {
    this.scheduleMenuOpen = Boolean(isOpen);
    this.dispatchEvent(new CustomEvent('change:schedule_menu', { detail: { open: this.scheduleMenuOpen } }));
  }

  announce(message) {
    if (typeof document !== 'undefined') {
      const el = document.getElementById('aria-announcements');
      if (el) {
        el.textContent = message;
      }
    }
  }
}

export { Store };
export const store = new Store();
