/**
 * keys.js - Keyboard Shortcuts Manager
 * Binds 1, 2, 3 (view switching), Space (expand/collapse), S, K, J, L, ⌘K, ?, T, Esc.
 */

export function initKeys(store, onMarkContact) {
  window.addEventListener('keydown', (e) => {
    // 1. Handle Command Palette (⌘K / Ctrl+K) from anywhere
    if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      store.setActiveModal(store.activeModal === 'palette' ? null : 'palette');
      return;
    }

    // 2. Escape closes any active modal, menu, or blur active input
    if (e.key === 'Escape') {
      if (store.scheduleMenuOpen) {
        store.setScheduleMenuOpen(false);
        return;
      }
      if (store.activeModal) {
        e.preventDefault();
        store.setActiveModal(null);
        return;
      }
      if (document.activeElement && (document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA')) {
        document.activeElement.blur();
        return;
      }
    }

    // 3. Ignore single-key hotkeys when typing in form inputs or modals
    const targetTag = e.target.tagName;
    if (targetTag === 'INPUT' || targetTag === 'TEXTAREA' || targetTag === 'SELECT' || e.target.isContentEditable) {
      return;
    }

    if (store.activeModal) {
      return; // Do not process workspace hotkeys when modal is active
    }

    // 4. View Switching: 1 (Today), 2 (Pipeline), 3 (Library)
    if (e.key === '1') {
      e.preventDefault();
      store.setView('today');
      return;
    }
    if (e.key === '2') {
      e.preventDefault();
      store.setView('pipeline');
      return;
    }
    if (e.key === '3') {
      e.preventDefault();
      store.setView('library');
      return;
    }
    if (e.key === '4') {
      e.preventDefault();
      store.setView('answers');
      return;
    }

    // 5. Space toggles card expansion in Send Queue
    if (e.key === ' ' || e.code === 'Space') {
      if (store.currentView === 'today') {
        const queue = store.getSendQueue();
        const contact = queue[store.queueIndex];
        if (contact) {
          e.preventDefault();
          store.toggleCardExpansion(contact.id);
          return;
        }
      }
    }

    // 6. Shortcuts Help Modal
    if (e.key === '?' || (e.shiftKey && e.key === '/')) {
      e.preventDefault();
      store.setActiveModal('shortcuts');
      return;
    }

    // 7. Theme Toggle
    if (e.key === 't' || e.key === 'T') {
      e.preventDefault();
      store.toggleTheme();
      return;
    }

    // 8. Queue Navigation (J = Next, L = Previous)
    if (e.key === 'j' || e.key === 'J') {
      e.preventDefault();
      store.setQueueIndex(store.queueIndex + 1);
      scrollToFocusedCard();
      return;
    }

    if (e.key === 'l' || e.key === 'L') {
      e.preventDefault();
      store.setQueueIndex(store.queueIndex - 1);
      scrollToFocusedCard();
      return;
    }

    // 9. Quick Actions (S = Sent, K = Skip contact)
    if (e.key === 's' || e.key === 'S') {
      e.preventDefault();
      const queue = store.getSendQueue();
      const contact = queue[store.queueIndex];
      if (contact && typeof onMarkContact === 'function') {
        onMarkContact(contact, 'SENT');
      }
      return;
    }

    if (e.key === 'k' || e.key === 'K') {
      e.preventDefault();
      const queue = store.getSendQueue();
      const contact = queue[store.queueIndex];
      if (contact && typeof onMarkContact === 'function') {
        onMarkContact(contact, 'SKIPPED');
      }
      return;
    }
  });

  function scrollToFocusedCard() {
    const focused = document.querySelector('.queue-row.focused');
    if (focused && typeof focused.scrollIntoView === 'function') {
      focused.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }
}
