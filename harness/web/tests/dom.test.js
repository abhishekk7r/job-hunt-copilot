import { describe, it, expect, beforeEach, afterEach } from 'bun:test';
import { normalizeChildren, h } from '../js/dom.js';

describe('normalizeChildren', () => {
  it('flattens nested arrays and drops null/undefined/boolean', () => {
    const raw = [
      'first',
      null,
      undefined,
      false,
      true,
      ['nested 1', ['deep nested 2', null]],
      { type: 'element' },
    ];
    const normalized = normalizeChildren(raw);
    expect(normalized.length).toBe(4);
    expect(normalized[0]).toBe('first');
    expect(normalized[1]).toBe('nested 1');
    expect(normalized[2]).toBe('deep nested 2');
    expect(normalized[3]).toEqual({ type: 'element' });
  });

  it('handles empty or non-array inputs cleanly', () => {
    expect(normalizeChildren([])).toEqual([]);
    expect(normalizeChildren(null)).toEqual([]);
    expect(normalizeChildren(undefined)).toEqual([]);
  });
});

// Minimal Fake DOM Node & Document implementation for Bun (zero external dependencies)
class FakeNode {
  constructor(nodeName, isText = false, textContent = '') {
    this.nodeName = nodeName;
    this.nodeType = isText ? 3 : 1;
    this.textContent = textContent;
    this.attributes = {};
    this.childNodes = [];
    this.children = [];
  }

  setAttribute(key, val) {
    this.attributes[key] = String(val);
  }

  getAttribute(key) {
    return this.attributes[key] || null;
  }

  appendChild(child) {
    this.childNodes.push(child);
    if (child.nodeType === 1) {
      this.children.push(child);
    }
    return child;
  }

  querySelectorAll(selector) {
    const res = [];
    function search(node) {
      for (const c of node.children) {
        if (selector.startsWith('.') && (c.className || '').includes(selector.slice(1))) {
          res.push(c);
        } else if (selector.startsWith('#') && c.getAttribute('id') === selector.slice(1)) {
          res.push(c);
        }
        search(c);
      }
    }
    search(this);
    return res;
  }
}

class FakeDocument {
  createElement(tag) {
    return new FakeNode(tag.toUpperCase());
  }
  createTextNode(text) {
    return new FakeNode('#text', true, String(text));
  }
}

describe('h() with fake document', () => {
  let originalDoc;

  beforeEach(() => {
    originalDoc = globalThis.document;
    globalThis.document = new FakeDocument();
  });

  afterEach(() => {
    globalThis.document = originalDoc;
  });

  it('flattens array children produced by .map() into parent element', () => {
    const items = ['Item 1', 'Item 2', 'Item 3'];
    const list = h('div', { className: 'review-group' },
      items.map(txt => h('div', { className: 'review-q' }, txt))
    );

    expect(list.children.length).toBe(3);
    expect(list.children[0].className).toBe('review-q');
  });

  it('renders nested elements correctly', () => {
    const card = h('div', { className: 'card' },
      h('h3', {}, 'Test Card'),
      h('p', {}, 'Card description')
    );

    expect(card.children.length).toBe(2);
    expect(card.children[0].childNodes[0].textContent).toBe('Test Card');
  });

  it('builds submit indicator badge with proper classes and accessibility attributes', () => {
    const liveBadge = h('button', {
      className: 'btn btn-sm badge-autoapply mode-live',
      id: 'badge-autoapply',
      'aria-label': 'Submit for real is ON. Click to immediately turn Off.',
      'aria-live': 'polite',
    },
      h('span', { className: 'badge-dot', 'aria-hidden': 'true' }, '●'),
      h('span', { id: 'badge-autoapply-text' }, 'SUBMIT: LIVE')
    );

    expect(liveBadge.className).toContain('mode-live');
    expect(liveBadge.getAttribute('aria-live')).toBe('polite');
    expect(liveBadge.children.length).toBe(2);
  });
});
