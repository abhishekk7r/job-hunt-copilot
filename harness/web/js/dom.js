/**
 * dom.js - Safe DOM element builder and tree normalization.
 * Flattens array children, drops falsy/null/undefined, and safely appends text and elements.
 */

export function normalizeChildren(children = []) {
  if (!Array.isArray(children)) return [];
  return children.flat(Infinity).filter(c => c !== null && c !== undefined && typeof c !== 'boolean');
}

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, val] of Object.entries(attrs)) {
    if (val === undefined || val === null) continue;
    if (key === 'className') {
      el.className = val;
    } else if (key.startsWith('data-') || key.startsWith('aria-') || key === 'role' || key === 'tabindex' || key === 'href' || key === 'target' || key === 'rel' || key === 'title' || key === 'type' || key === 'placeholder' || key === 'htmlFor' || key === 'for' || key === 'rows' || key === 'checked') {
      if (key === 'checked') {
        if (Boolean(val)) {
          el.setAttribute('checked', '');
          el.checked = true;
        }
      } else {
        el.setAttribute(key === 'htmlFor' ? 'for' : key, val);
      }
    } else {
      el.setAttribute(key, val);
    }
  }

  const normalized = normalizeChildren(children);
  for (const child of normalized) {
    if (typeof child === 'string' || typeof child === 'number') {
      el.appendChild(document.createTextNode(String(child)));
    } else if (child && typeof child === 'object' && ('nodeType' in child || 'appendChild' in child)) {
      el.appendChild(child);
    }
  }

  return el;
}
