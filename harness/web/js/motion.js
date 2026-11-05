/**
 * motion.js - Motion & Animation Utilities
 * Adheres to MOTION_INTENSITY=5, prefers-reduced-motion, only transforms & opacity.
 */

export function prefersReducedMotion() {
  return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Animates a numeric counter smoothly over duration (default 600ms ease-out).
 * @param {HTMLElement} element
 * @param {number} targetVal
 * @param {number} duration
 */
export function animateCountUp(element, targetVal, duration = 600) {
  if (!element) return;
  const target = Math.round(Number(targetVal) || 0);

  if (prefersReducedMotion()) {
    element.textContent = String(target);
    return;
  }

  const start = Math.round(Number(element.textContent) || 0);
  if (start === target) return;

  const startTime = performance.now();

  function easeOutCubic(t) {
    return 1 - Math.pow(1 - t, 3);
  }

  function frame(currentTime) {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);
    const eased = easeOutCubic(progress);
    const current = Math.round(start + (target - start) * eased);
    element.textContent = String(current);

    if (progress < 1) {
      requestAnimationFrame(frame);
    } else {
      element.textContent = String(target);
    }
  }

  requestAnimationFrame(frame);
}

/**
 * Performs a FLIP animation when a card in a vertical list is removed.
 * @param {HTMLElement} elementToCollapse
 * @param {HTMLElement} container
 * @param {() => void} onDone
 */
export function flipRemove(elementToCollapse, container, onDone) {
  if (!elementToCollapse || !container) {
    if (onDone) onDone();
    return;
  }

  if (prefersReducedMotion()) {
    elementToCollapse.remove();
    if (onDone) onDone();
    return;
  }

  const items = Array.from(container.children);
  const firstTops = new Map();
  items.forEach(item => {
    firstTops.set(item, item.getBoundingClientRect().top);
  });

  // 1. Animate out the active card
  elementToCollapse.style.transition = 'opacity 180ms ease, transform 180ms ease';
  elementToCollapse.style.opacity = '0';
  elementToCollapse.style.transform = 'scale(0.96) translateY(-8px)';

  setTimeout(() => {
    elementToCollapse.remove();

    // 2. Measure new positions of remaining items
    const remaining = Array.from(container.children);
    remaining.forEach(item => {
      const firstTop = firstTops.get(item);
      const lastTop = item.getBoundingClientRect().top;
      const deltaY = firstTop - lastTop;

      if (deltaY !== 0) {
        item.style.transition = 'none';
        item.style.transform = `translateY(${deltaY}px)`;
      }
    });

    // 3. Invert -> Play
    requestAnimationFrame(() => {
      remaining.forEach(item => {
        item.style.transition = 'transform 260ms cubic-bezier(0.16, 1, 0.3, 1)';
        item.style.transform = '';
      });
      setTimeout(() => {
        remaining.forEach(item => {
          item.style.transition = '';
        });
        if (onDone) onDone();
      }, 270);
    });
  }, 190);
}
