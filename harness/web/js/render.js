/**
 * render.js - High-Performance Safe DOM Renderer
 * ZERO innerHTML on untrusted strings. Uses createElement/textContent.
 * Sentence case, compact rows (<=64px), three-view information architecture.
 */

import { animateCountUp } from './motion.js';
import { fetchAnswer } from './api.js';
import { h } from './dom.js';

const STATUS_LABELS = {
  TO_APPLY: 'To apply',
  BLOCKED_USER: 'Needs you',
  OUTREACH_DRAFTED: 'Outreach drafted',
  APPLIED: 'Applied',
  COMPANY_SITE_ONLY: 'Company site',
  REJECTED: 'Rejected',
  RANKED_OUT: 'Ranked out',
  HALTED: 'Halted',
  PREFILLED: 'Ready to send',
  SENT: 'Sent',
  SKIPPED: 'Skipped',
  PROPOSED: 'Proposed',
};

function createStatusPill(status) {
  const label = STATUS_LABELS[status] || status;
  return h('span', { className: `pill s-${status}` }, label);
}

export function renderCommandBar(state, store) {
  if (!state) return;
  const ks = Array.isArray(state.kill_switch) && state.kill_switch.length > 0 ? state.kill_switch[0] : null;
  const ksOn = Boolean(ks && ks.on);

  const dot = document.getElementById('status-dot');
  const txt = document.getElementById('status-text');

  if (dot && txt) {
    if (ksOn) {
      dot.className = 'status-dot halt';
      txt.textContent = 'Halted (kill switch engaged)';
    } else if (state.cycle_running) {
      dot.className = 'status-dot running';
      txt.textContent = 'Cycle running right now';
    } else {
      const scheduleActive = state.settings ? Boolean(state.settings['ctl:schedule']) : (state.schedule?.enabled !== false);
      if (!scheduleActive) {
        dot.className = 'status-dot';
        txt.textContent = 'Idle. Schedule paused.';
      } else {
        dot.className = 'status-dot ok';
        const sch = state.schedule || {};
        const dueMs = sch.next_due ? sch.next_due * 1000 : null;
        if (dueMs) {
          const diffSec = Math.max(0, Math.floor((dueMs - Date.now()) / 1000));
          const h = Math.floor(diffSec / 3600);
          const m = Math.floor((diffSec % 3600) / 60);
          txt.textContent = `Idle. Next run in ~${h > 0 ? `${h}h ` : ''}${m}m.`;
        } else {
          txt.textContent = 'Idle. Next run pending.';
        }
      }
    }
  }

  // Segmented control active tab state
  const tabs = document.querySelectorAll('.segmented-control .seg-btn');
  tabs.forEach(tab => {
    const v = tab.getAttribute('data-view');
    const isActive = v === store.currentView;
    tab.classList.toggle('active', isActive);
    tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
  });

  // Schedule dropdown menu items
  const settings = state.settings || {};
  const btnSched = document.getElementById('btn-toggle-schedule');
  const btnPortals = document.getElementById('btn-toggle-portals');
  const btnPeople = document.getElementById('btn-toggle-people');

  if (btnSched) {
    const on = Boolean(settings['ctl:schedule']);
    btnSched.textContent = `6-hourly cycle: ${on ? 'Active' : 'Paused'}`;
    btnSched.classList.toggle('active', on);
  }
  if (btnPortals) {
    const on = Boolean(settings['ctl:portals']);
    btnPortals.textContent = `Portals (Naukri, Instahyre): ${on ? 'Active' : 'Paused'}`;
    btnPortals.classList.toggle('active', on);
  }
  if (btnPeople) {
    const on = Boolean(settings['ctl:people']);
    btnPeople.textContent = `People networking: ${on ? 'Active' : 'Paused'}`;
    btnPeople.classList.toggle('active', on);
  }
  const btnSubmit = document.getElementById('btn-toggle-submit');
  if (btnSubmit) {
    const isSubmit = Number(settings['ctl:submit'] || 0) === 1;
    if (!btnSubmit.dataset.confirming) {
      btnSubmit.textContent = `Submit for real: ${isSubmit ? 'On' : 'Off'}`;
    }
    btnSubmit.classList.toggle('active', isSubmit);
    btnSubmit.dataset.mode = String(isSubmit ? 1 : 0);
  }

  // Persistent Submit Indicator Badge in Header (when submit is ON)
  const badgeAutoapply = document.getElementById('badge-autoapply');
  const badgeText = document.getElementById('badge-autoapply-text');
  if (badgeAutoapply && badgeText) {
    const isSubmit = Number(settings['ctl:submit'] || 0) === 1;
    const prevMode = Number(badgeAutoapply.dataset.mode ?? -1);
    badgeAutoapply.dataset.mode = String(isSubmit ? 1 : 0);

    if (!isSubmit) {
      badgeAutoapply.hidden = true;
      badgeAutoapply.className = 'btn btn-sm badge-autoapply';
      badgeText.textContent = 'SUBMIT: OFF';
      badgeAutoapply.title = 'Submit for real is Off';
      if (prevMode === 1) {
        store.announce('Submit for real turned off');
      }
    } else {
      badgeAutoapply.hidden = false;
      badgeAutoapply.className = 'btn btn-sm badge-autoapply mode-live';
      badgeText.textContent = 'SUBMIT: LIVE';
      badgeAutoapply.title = 'Submit for real is ON (submitting applications). Click to turn Off immediately.';
      if (prevMode !== 1) {
        store.announce('Warning: Submit for real is On');
      }
    }
  }

  // Kill switch button text & state
  const ksBtn = document.getElementById('btn-killswitch');
  const ksTxt = document.getElementById('kill-text');
  if (ksBtn && ksTxt) {
    if (ksOn) {
      ksTxt.textContent = 'Release kill switch';
      ksBtn.classList.add('active-halt');
    } else {
      ksTxt.textContent = 'Kill switch';
      ksBtn.classList.remove('active-halt');
    }
  }
}

let cycleIntervalId = null;

export function renderCycleRing(state) {
  if (!state) return;
  const countdownEl = document.getElementById('cycle-countdown');
  const arcEl = document.getElementById('cycle-arc');
  if (!countdownEl || !arcEl) return;

  // Next run comes from the server's DB schedule (system clock), not from the last run's start.
  const sch = state.schedule || {};
  const INTERVAL_MS = (sch.interval_min || 360) * 60 * 1000;
  const offset = sch.now ? (Date.now() - sch.now * 1000) : 0; // browser vs server clock skew
  const dueMs = sch.next_due ? sch.next_due * 1000 + offset : null;
  const paused = sch.enabled === false;
  let startTime = dueMs ? dueMs - INTERVAL_MS : null;

  function update() {
    if (paused || !startTime) {
      countdownEl.textContent = paused ? 'paused' : '--:--:--';
      arcEl.setAttribute('stroke-dashoffset', '100');
      const statusTxt = document.getElementById('status-text');
      const ks = Array.isArray(state?.kill_switch) && state.kill_switch.length > 0 ? state.kill_switch[0] : null;
      if (statusTxt && !ks?.on && !state?.cycle_running && paused) {
        statusTxt.textContent = 'Idle. Schedule paused.';
      }
      return;
    }

    const now = Date.now();
    const remaining = Math.max(0, dueMs - now);

    const totalSeconds = Math.floor(remaining / 1000);
    const hrs = String(Math.floor(totalSeconds / 3600)).padStart(2, '0');
    const mins = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, '0');
    const secs = String(totalSeconds % 60).padStart(2, '0');
    countdownEl.textContent = `${hrs}:${mins}:${secs}`;

    const percentElapsed = ((INTERVAL_MS - remaining) / INTERVAL_MS) * 100;
    const offset = Math.max(0, Math.min(100, 100 - percentElapsed));
    arcEl.setAttribute('stroke-dashoffset', offset.toFixed(1));

    // Update status sentence with remaining time
    const statusTxt = document.getElementById('status-text');
    const ks = Array.isArray(state?.kill_switch) && state.kill_switch.length > 0 ? state.kill_switch[0] : null;
    if (statusTxt && !ks?.on && !state?.cycle_running) {
      const hStr = Math.floor(totalSeconds / 3600);
      const mStr = Math.floor((totalSeconds % 3600) / 60);
      statusTxt.textContent = `Idle. Next run in ${hStr}h ${mStr}m.`;
    }
  }

  if (cycleIntervalId) clearInterval(cycleIntervalId);
  update();
  cycleIntervalId = setInterval(update, 1000);
}

export function renderHeroStrip(state, store) {
  if (!state) return;
  const contacts = state.contacts || [];
  const jobs = state.jobs || [];

  const toSend = contacts.filter(c => c.status === 'PREFILLED').length;
  const applied = jobs.filter(j => j.status === 'APPLIED').length;
  const blocked = jobs.filter(j => j.status === 'BLOCKED_USER' || (j.blocker_note && j.status !== 'APPLIED' && j.status !== 'REJECTED' && j.status !== 'RANKED_OUT')).length;
  const pendingDecisions = store?.getPendingDecisions()?.length || 0;
  const totalNeeds = blocked + pendingDecisions;

  animateCountUp(document.getElementById('stat-to-send'), toSend);
  animateCountUp(document.getElementById('stat-applied'), applied);
  animateCountUp(document.getElementById('stat-blocked'), totalNeeds);
}

export function renderSendQueue(state, store) {
  const container = document.getElementById('queue-card-list');
  const countBadge = document.getElementById('queue-count-badge');
  if (!container) return;

  const queue = store.getSendQueue();
  if (countBadge) countBadge.textContent = `${queue.length} ready to send`;

  container.replaceChildren();

  if (queue.length === 0) {
    const empty = h('div', { className: 'hero-subtext empty-note' },
      'No prefilled tabs waiting. Press Send in Chrome, then mark them here.'
    );
    container.appendChild(empty);
    return;
  }

  queue.forEach((contact, idx) => {
    const isFocused = idx === store.queueIndex;
    const isExpanded = store.expandedContactIds.has(contact.id);
    const isSenior = store.isSenior(contact);
    const isWarm = Boolean(contact.job_id);

    // CRITICAL: use note_text ONLY, never contact.note (A1)
    const noteText = contact.note_text || 'No personalized message text stored.';

    const row = h('div', {
      className: `queue-row ${isFocused ? 'focused' : ''} ${isExpanded ? 'expanded' : ''}`,
      'data-id': contact.id,
      tabindex: '0',
      role: 'listitem',
    });

    // Main 1-line collapsed bar (height <= 64px)
    const chevron = h('span', { className: 'queue-expand-icon' }, '›');
    const nameEl = h('span', { className: 'queue-name' }, contact.name || 'Unnamed contact');
    const subText = `${contact.title || 'Technical Role'} at ${contact.current_company || 'Target company'}`;
    const subEl = h('span', { className: 'queue-sub', title: subText }, subText);

    const leftCluster = h('div', { className: 'queue-row-left' },
      chevron,
      nameEl,
      subEl,
      isWarm ? h('span', { className: 'pill pill-sm' }, 'Applied here') : null,
      isSenior ? h('span', { className: 'pill pill-warn pill-sm' }, 'Senior') : null
    );

    // Right cluster buttons
    const copyBtn = h('button', {
      type: 'button',
      className: 'btn btn-sm btn-outline',
      'aria-label': `Copy outreach note for ${contact.name}`,
    }, 'Copy note');

    copyBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      try {
        await navigator.clipboard.writeText(noteText);
        copyBtn.textContent = 'Copied!';
        setTimeout(() => { copyBtn.textContent = 'Copy note'; }, 1500);
      } catch (_) {}
    });

    const sentBtn = h('button', {
      type: 'button',
      className: 'btn btn-sm btn-primary btn-mark-action',
      'data-id': contact.id,
      'data-action': 'SENT',
      'aria-label': `Confirm I sent outreach message to ${contact.name}`,
    }, 'Sent');

    const skipBtn = h('button', {
      type: 'button',
      className: 'btn btn-sm btn-outline btn-mark-action',
      'data-id': contact.id,
      'data-action': 'SKIPPED',
      'aria-label': `Skip outreach message for ${contact.name}`,
    }, 'Skip');

    const actions = h('div', { className: 'queue-row-actions' },
      copyBtn,
      sentBtn,
      skipBtn
    );

    const mainRow = h('div', { className: 'queue-row-main' },
      leftCluster,
      actions
    );

    // Expandable drawer: full note_text and profile link (internal note tag NEVER exposed)
    const drawer = h('div', { className: 'queue-drawer' },
      h('div', { className: 'queue-note-text' }, noteText),
      h('div', { className: 'row-between' },
        h('span', { className: 'hero-subtext' }, `${noteText.length} characters (limit 300)`),
        contact.profile_url ? h('a', {
          href: contact.profile_url,
          target: '_blank',
          rel: 'noopener noreferrer',
          className: 'hero-subtext',
          'aria-label': `Open LinkedIn profile for ${contact.name}`,
        }, 'Profile ↗') : null
      )
    );

    row.appendChild(mainRow);
    row.appendChild(drawer);

    // Click on row toggles expansion; buttons stop propagation
    row.addEventListener('click', (e) => {
      if (e.target.closest('button') || e.target.closest('a')) return;
      store.setQueueIndex(idx);
      store.toggleCardExpansion(contact.id);
    });

    container.appendChild(row);
  });
}

export function renderNeedsYou(state, store) {
  const list = document.getElementById('blocker-list');
  const badge = document.getElementById('blocker-count-badge');

  const jobs = state?.jobs || [];
  const blocked = jobs.filter(j => j.status === 'BLOCKED_USER' || (j.blocker_note && j.status !== 'APPLIED' && j.status !== 'REJECTED' && j.status !== 'RANKED_OUT'));

  const totalNeeds = blocked.length;
  if (badge) {
    badge.textContent = `${totalNeeds} needed`;
    badge.className = totalNeeds > 0 ? 'pill pill-warn' : 'pill pill-ok';
  }

  // Render Blocked Jobs List
  if (list) {
    list.replaceChildren();
    if (blocked.length === 0) {
      if (pendingDecisions.length === 0) {
        list.appendChild(h('li', { className: 'hero-subtext' }, 'Nothing currently blocked.'));
      }
      return;
    }

    blocked.forEach(job => {
      const rawNote = job.blocker_note || 'Intervention needed';
      const truncatedNote = rawNote.length > 80 ? `${rawNote.slice(0, 80)}...` : rawNote;

      const li = h('li', { className: 'li-row li-split' },
        h('div', { className: 'minw0' },
          h('b', {}, `${job.company} — ${job.role}: `),
          h('span', { className: 'hero-subtext crit', title: rawNote }, truncatedNote)
        ),
        job.job_url ? h('a', {
          href: job.job_url,
          target: '_blank',
          rel: 'noopener noreferrer',
          className: 'hero-subtext noshrink',
          'aria-label': `Open job posting for ${job.company}`
        }, 'Posting ↗') : null
      );
      list.appendChild(li);
    });
  }
}

export function renderFunnelRibbon(state, store) {
  const container = document.getElementById('funnel-container');
  if (!container || !state) return;

  const jobs = state.jobs || [];
  const counts = {
    TO_APPLY: 0,
    APPLIED: 0,
    BLOCKED_USER: 0,
    REJECTED: 0,
  };
  jobs.forEach(j => {
    if (counts[j.status] !== undefined) counts[j.status]++;
  });

  const ribbon = h('div', {
    className: 'ribbon',
    role: 'group',
    'aria-label': 'Pipeline funnel stages'
  });

  const stages = [
    { key: 'TO_APPLY', label: 'To apply' },
    { key: 'APPLIED', label: 'Applied' },
    { key: 'BLOCKED_USER', label: 'Needs you' },
    { key: 'REJECTED', label: 'Rejected' },
  ];

  stages.forEach(({ key, label }) => {
    const count = counts[key] || 0;
    const isActive = store.jobsFilter === key;
    const chip = h('button', {
      type: 'button',
      className: `filter-chip ${isActive ? 'active' : ''}`,
      'aria-label': `Filter jobs by ${label} (${count})`,
    }, `${label} (${count})`);

    chip.addEventListener('click', () => {
      store.setJobsFilter(store.jobsFilter === key ? '' : key);
    });

    ribbon.appendChild(chip);
  });

  container.replaceChildren(ribbon);
}

function localDay(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export function matchesDate(updatedAt, range, now = new Date()) {
  if (!range) return true;
  if (!updatedAt) return false;
  const t = new Date(/Z|[+-]\d\d:?\d\d$/.test(updatedAt) ? updatedAt : `${updatedAt}Z`);
  if (Number.isNaN(t.getTime())) return false;
  const day = localDay(t);
  if (range === 'today') return day === localDay(now);
  if (range === 'yesterday') return day === localDay(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1));
  if (range === '7d') return t >= new Date(now.getFullYear(), now.getMonth(), now.getDate() - 6);
  return true;
}

export function renderJobsTable(state, store) {
  const tbody = document.getElementById('jobs-table-body');
  if (!tbody || !state) return;

  const jobs = state.jobs || [];
  const filter = store.jobsFilter;
  const query = store.jobsSearch;

  const filtered = jobs.filter(j => {
    if (filter && j.status !== filter) return false;
    if (!matchesDate(j.updated_at, store.jobsDate)) return false;
    if (query) {
      const matchText = `${j.company || ''} ${j.role || ''} ${j.id || ''} ${j.platform || ''}`.toLowerCase();
      if (!matchText.includes(query)) return false;
    }
    return true;
  });

  tbody.replaceChildren();

  if (filtered.length === 0) {
    tbody.appendChild(h('tr', {},
      h('td', { colspan: '10', className: 'hero-subtext empty-note' }, 'No matching jobs found.')
    ));
    return;
  }

  filtered.forEach(j => {
    const tr = h('tr', { 'data-status': j.status },
      h('td', { className: 'mono' }, String(j.id)),
      h('td', {}, h('b', {}, j.company || '—')),
      h('td', {}, j.job_url ? h('a', {
        href: j.job_url,
        target: '_blank',
        rel: 'noopener noreferrer',
        'aria-label': `View posting for ${j.role} at ${j.company}`,
      }, j.role || 'Posting') : (j.role || '—')),
      h('td', {}, createStatusPill(j.status)),
      h('td', { className: 'mono' }, j.tier ? `T${j.tier}` : '—'),
      h('td', {}, j.platform || '—'),
      h('td', { className: 'mono' }, j.rank_score !== null && j.rank_score !== undefined ? String(j.rank_score) : '—'),
      h('td', {}, j.recruiter_name || '—'),
      h('td', { className: 'mono' }, j.date_applied || '—'),
      h('td', { className: 'mono hero-subtext' }, (j.updated_at || '').slice(0, 16).replace('T', ' '))
    );
    tbody.appendChild(tr);
  });
}

export function renderLibraryAccordions(state, store) {
  if (!state) return;

  // 1. All Contacts
  const contacts = state.contacts || [];
  const countContactsEl = document.getElementById('lib-contacts-count');
  if (countContactsEl) countContactsEl.textContent = String(contacts.length);

  const contactsBody = document.getElementById('contacts-table-body');
  if (contactsBody) {
    contactsBody.replaceChildren();
    contacts.forEach(c => {
      contactsBody.appendChild(h('tr', {},
        h('td', {}, h('b', {}, c.name || '—')),
        h('td', {}, c.title || '—'),
        h('td', {}, c.current_company || '—'),
        h('td', {}, h('span', { className: 'pill' }, STATUS_LABELS[c.status] || c.status || 'Proposed')),
        h('td', { className: 'mono' }, String(c.score || 0)),
        h('td', {}, c.profile_url ? h('a', {
          href: c.profile_url,
          target: '_blank',
          rel: 'noopener noreferrer',
          'aria-label': `Open LinkedIn profile for ${c.name}`,
        }, 'Profile ↗') : '—')
      ));
    });
  }

  // 2. Email Drafts
  const drafts = state.email_drafts || [];
  const countDraftsEl = document.getElementById('lib-drafts-count');
  if (countDraftsEl) countDraftsEl.textContent = String(drafts.length);

  const emailList = document.getElementById('email-drafts-list');
  if (emailList) {
    emailList.replaceChildren();
    drafts.forEach(d => {
      emailList.appendChild(h('li', { className: 'lib-row' },
        h('details', { className: 'lib-item' },
          h('summary', { className: 'lib-item-head' },
            h('b', {}, d.company || 'Company'),
            h('span', { className: 'lib-item-sub' }, `${d.contact_name || 'Contact'} · ${d.to_email || 'no address yet'}`),
            h('span', { className: 'pill' }, d.status || 'Draft')
          ),
          h('div', { className: 'lib-item-subject' }, d.subject || ''),
          h('pre', { className: 'msg-body' }, d.body || '')
        )
      ));
    });
  }

  // 3. Queued Outreach Messages (Approval queue)
  const outreach = state.outreach || [];
  const countQueuedEl = document.getElementById('lib-queued-count');
  if (countQueuedEl) countQueuedEl.textContent = String(outreach.length);

  const approvalList = document.getElementById('approval-queue-list');
  if (approvalList) {
    approvalList.replaceChildren();
    outreach.forEach(o => {
      const raw = o.rendered_message || '';
      const m = raw.match(/^\s*Subject:\s*(.*?)\s*(?:\n|$)/i);
      const subject = m ? m[1] : '';
      const body = m ? raw.slice(m[0].length).trim() : raw;
      approvalList.appendChild(h('li', { className: 'lib-row' },
        h('details', { className: 'lib-item' },
          h('summary', { className: 'lib-item-head' },
            h('b', {}, o.company || 'Company'),
            h('span', { className: 'lib-item-sub' }, `${o.recruiter_name || 'Recruiter'} · ${o.channel || 'LinkedIn'} · ${o.char_count || raw.length} chars`),
            h('span', { className: 'pill' }, (o.approval_status || 'Pending').replace(/_/g, ' ').toLowerCase())
          ),
          subject ? h('div', { className: 'lib-item-subject' }, subject) : null,
          h('pre', { className: 'msg-body' }, body)
        )
      ));
    });
  }

  // 4 & 5. Reveal-on-demand answers (shared builder)
  function answerRow(titleText, subText, statusText, fetchKey, ariaName) {
    const answerBox = h('pre', { className: 'answer-box' });
    const revealBtn = h('button', {
      type: 'button',
      className: 'btn btn-sm btn-outline',
      'aria-label': `Reveal answer for ${ariaName}`,
    }, 'Show');
    revealBtn.addEventListener('click', async () => {
      if (answerBox.classList.contains('open')) {
        answerBox.classList.remove('open');
        revealBtn.textContent = 'Show';
        return;
      }
      revealBtn.textContent = 'Loading…';
      try {
        const res = await fetchAnswer(fetchKey);
        answerBox.textContent = res.answer || '(Empty answer)';
        answerBox.classList.add('open');
        revealBtn.textContent = 'Hide';
      } catch (_) {
        revealBtn.textContent = 'Failed, retry';
      }
    });
    return h('li', { className: 'lib-row' },
      h('div', { className: 'ans-head' },
        h('div', { className: 'ans-title' },
          h('b', { className: 'mono' }, titleText),
          subText ? h('span', { className: 'lib-item-sub' }, subText) : null,
          statusText ? h('span', { className: 'pill' }, statusText) : null
        ),
        revealBtn
      ),
      answerBox
    );
  }

  // 4. Application Answers
  const appAnswers = state.app_answers || [];
  const countAppAnsEl = document.getElementById('lib-app-answers-count');
  if (countAppAnsEl) countAppAnsEl.textContent = String(appAnswers.length);

  const appAnsList = document.getElementById('app-answers-list');
  if (appAnsList) {
    appAnsList.replaceChildren();
    appAnswers.forEach(ans => {
      const q = (ans.question || '');
      appAnsList.appendChild(answerRow(
        ans.application, q.length > 90 ? `${q.slice(0, 90)}…` : q,
        (ans.status || 'Saved').replace(/_/g, ' ').toLowerCase(), ans.id, ans.application
      ));
    });
  }

  // 5. Screening Answers
  const screening = state.screening || [];
  const countScreeningEl = document.getElementById('lib-screening-count');
  if (countScreeningEl) countScreeningEl.textContent = String(screening.length);

  const screeningList = document.getElementById('screening-qa-list');
  if (screeningList) {
    screeningList.replaceChildren();
    screening.forEach(qa => {
      screeningList.appendChild(answerRow(qa.question_key, '', '', qa.question_key, qa.question_key));
    });
  }

  // 6. Gmail Drafts Snapshot
  const snaps = state.gmail_snapshot || [];
  const countGmailEl = document.getElementById('lib-gmail-count');
  if (countGmailEl) countGmailEl.textContent = String(snaps.length);

  const gmailList = document.getElementById('gmail-snapshot-list');
  if (gmailList) {
    gmailList.replaceChildren();
    snaps.forEach(g => {
      gmailList.appendChild(h('li', { className: 'lib-row' },
        h('b', {}, `${g.account || 'Account'}: `),
        `${g.subject || ''} `,
        g.to_addr ? `to ${g.to_addr} ` : '',
        g.note ? h('span', { className: 'hero-subtext' }, `(${g.note})`) : null
      ));
    });
  }

  // 7. Open Items
  const items = state.open_items || [];
  const countOpenEl = document.getElementById('lib-open-items-count');
  if (countOpenEl) countOpenEl.textContent = String(items.length);

  const savedItemsList = document.getElementById('saved-items-list');
  if (savedItemsList) {
    savedItemsList.replaceChildren();
    items.forEach(it => {
      savedItemsList.appendChild(h('li', { className: 'lib-row' },
        h('span', { className: 'pill pill-gap' }, it.status || 'Open'),
        h('b', {}, `${it.area || 'General'}: `),
        it.item || ''
      ));
    });
  }

  // 8. Run History
  const runs = state.run_log || [];
  const countRunsEl = document.getElementById('lib-runs-count');
  if (countRunsEl) countRunsEl.textContent = String(runs.length);

  const runsList = document.getElementById('runs-list');
  if (runsList) {
    runsList.replaceChildren();
    runs.forEach(r => {
      const isHalted = r.status === 'HALTED' || Boolean(r.halted_reason);
      runsList.appendChild(h('li', { className: 'lib-row' },
        h('div', { className: 'ans-title' },
          h('b', {}, r.mode || 'run'),
          h('span', { className: 'hero-subtext' }, `(${r.run_id || ''})`),
          h('span', { className: `pill ${isHalted ? 'pill-crit' : 'pill-ok'}` }, r.status || 'Done'),
          h('span', { className: 'mono hero-subtext' }, (r.started_at || '').slice(0, 19).replace('T', ' '))
        ),
        isHalted && r.halted_reason ? h('p', { className: 'crit halt-line' },
          h('b', {}, 'Halted: '),
          r.halted_reason
        ) : null
      ));
    });
  }

  // System provenance
  const parityEl = document.getElementById('data-parity-badge');
  const nextCycleEl = document.getElementById('next-cycle-text');
  const creditsEl = document.getElementById('inmail-credits-badge');
  const cycleRunningEl = document.getElementById('cycle-running-indicator');

  if (parityEl) parityEl.textContent = state.parity || 'Parity OK';
  if (nextCycleEl) nextCycleEl.textContent = state.next_cycle || 'Computing...';
  if (creditsEl) creditsEl.textContent = state.budgets?.inmail_credits ?? '–';
  if (cycleRunningEl) cycleRunningEl.style.display = state.cycle_running ? 'block' : 'none';
}

export function renderUndoBanner(pendingUndo) {
  const banner = document.getElementById('undo-toast') || document.getElementById('undo-banner');
  const msgEl = document.getElementById('undo-message');
  const btnUndo = document.getElementById('btn-undo-action');
  if (!banner || !msgEl || !btnUndo) return;

  if (pendingUndo) {
    const remainingSecs = Math.max(1, Math.ceil((pendingUndo.expiresAt - Date.now()) / 1000));
    if (pendingUndo.message) {
      msgEl.textContent = pendingUndo.message;
    } else if (pendingUndo.contact) {
      msgEl.textContent = `Marked ${pendingUndo.contact.name || 'contact'} as ${pendingUndo.status}`;
    } else {
      msgEl.textContent = 'Action pending';
    }
    btnUndo.textContent = `Undo (${remainingSecs}s)`;
    banner.classList.add('active');
  } else {
    banner.classList.remove('active');
  }
}

export function renderProgressPanel(store) {
  const panel = document.getElementById('run-progress-panel');
  if (!panel) return;

  const dot = document.getElementById('progress-status-dot');
  const summaryText = document.getElementById('progress-summary-text');
  const runLog = store?.data?.run_log;

  if (!runLog || runLog.length === 0) {
    if (dot) dot.className = 'status-dot idle';
    if (summaryText) summaryText.textContent = 'Last run: Idle';
    panel.className = 'card run-progress-panel idle';
    return;
  }

  const latest = runLog[0];
  const st = String(latest.status || '');
  const isRunning = st.startsWith('RUNNING') || Boolean(store?.data?.cycle_running);

  if (isRunning) {
    let phase = 'cycle';
    if (st.includes(':')) {
      phase = st.split(':', 2)[1].trim();
    }
    const since = latest.started_at ? formatTimeAgo(latest.started_at) : '';
    const text = since ? `Running: ${phase} since ${since}` : `Running: ${phase}`;
    if (summaryText) summaryText.textContent = text;
    if (dot) dot.className = 'status-dot running';
    panel.className = 'card run-progress-panel running';
  } else {
    const timeStr = latest.ended_at ? formatTimeAgo(latest.ended_at) : (latest.started_at ? formatTimeAgo(latest.started_at) : '');
    const reasonStr = (st === 'HALTED' && latest.halted_reason) ? ` (${latest.halted_reason})` : '';
    const text = `Last run: ${st}${reasonStr}${timeStr ? ' ' + timeStr : ''}`;
    if (summaryText) summaryText.textContent = text;
    if (dot) {
      dot.className = 'status-dot';
      if (st === 'COMPLETED') dot.classList.add('ok');
      else if (st === 'HALTED' || st === 'ERROR') dot.classList.add('halt');
      else dot.classList.add('idle');
    }
    panel.className = 'card run-progress-panel idle';
  }
}

function formatTimeAgo(isoString) {
  try {
    const dt = new Date(isoString);
    if (isNaN(dt.getTime())) return '';
    const diffMs = Date.now() - dt.getTime();
    const diffSecs = Math.max(0, Math.floor(diffMs / 1000));
    if (diffSecs < 60) return 'just now';
    const diffMins = Math.floor(diffSecs / 60);
    if (diffMins < 60) return `${diffMins} min ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours} hour${diffHours > 1 ? 's' : ''} ago`;
    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays} day${diffDays > 1 ? 's' : ''} ago`;
  } catch (_) {
    return '';
  }
}

export function renderAnswersTable(answers, onAction) {
  const tbody = document.getElementById('answers-table-body');
  const countBadge = document.getElementById('answers-count-badge');
  if (!tbody) return;

  tbody.replaceChildren();

  const list = answers || [];
  if (countBadge) {
    countBadge.textContent = `${list.length} drafted`;
  }

  if (list.length === 0) {
    const tr = h('tr', {}, [
      h('td', { colSpan: 5, className: 'u-text-center u-muted u-p16' }, 'No drafted answers to review.')
    ]);
    tbody.appendChild(tr);
    return;
  }

  list.forEach(ans => {
    const inputAnswer = h('input', {
      type: 'text',
      className: 'input-answer-edit',
      value: ans.answer || '',
      'aria-label': `Edit answer for: ${ans.question}`,
    });

    const btnApprove = h('button', {
      type: 'button',
      className: 'btn btn-sm btn-primary',
      'aria-label': `Approve answer #${ans.id}`,
    }, 'Approve');

    const btnEdit = h('button', {
      type: 'button',
      className: 'btn btn-sm',
      'aria-label': `Save edited answer #${ans.id}`,
    }, 'Save');

    const btnRetire = h('button', {
      type: 'button',
      className: 'btn btn-sm btn-danger',
      'aria-label': `Retire answer #${ans.id}`,
    }, 'Retire');

    btnApprove.addEventListener('click', () => {
      if (typeof onAction === 'function') {
        onAction(ans.id, 'approve', inputAnswer.value);
      }
    });

    btnEdit.addEventListener('click', () => {
      if (typeof onAction === 'function') {
        onAction(ans.id, 'edit', inputAnswer.value);
      }
    });

    btnRetire.addEventListener('click', () => {
      if (typeof onAction === 'function') {
        onAction(ans.id, 'retire');
      }
    });

    const actionsCell = h('div', { className: 'actions-cell-wrap' }, [
      btnApprove,
      btnEdit,
      btnRetire
    ]);

    const tr = h('tr', { 'data-id': String(ans.id) }, [
      h('td', { className: 'u-font-mono u-break' }, ans.question || ''),
      h('td', { className: 'td-answer-edit' }, [inputAnswer]),
      h('td', {}, ans.kind || ''),
      h('td', { className: 'u-muted' }, ans.source || ''),
      h('td', {}, [actionsCell])
    ]);

    tbody.appendChild(tr);
  });
}
