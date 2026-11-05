import { test, expect } from 'bun:test';
import { matchesDate } from '../js/render.js';

const now = new Date(2026, 10, 3, 12, 0, 0);
const local = (y, m, d, hh = 9) => new Date(y, m, d, hh).toISOString();

test('any date matches everything', () => {
  expect(matchesDate('', '', now)).toBe(true);
});
test('today / yesterday / 7d', () => {
  expect(matchesDate(local(2026, 10, 3), 'today', now)).toBe(true);
  expect(matchesDate(local(2026, 10, 2), 'today', now)).toBe(false);
  expect(matchesDate(local(2026, 10, 2), 'yesterday', now)).toBe(true);
  expect(matchesDate(local(2026, 10, 1), 'yesterday', now)).toBe(false);
  expect(matchesDate(local(2026, 9, 28), '7d', now)).toBe(true);
  expect(matchesDate(local(2026, 9, 20), '7d', now)).toBe(false);
});
test('naive timestamps are UTC; bad ones do not match', () => {
  expect(matchesDate('garbage', 'today', now)).toBe(false);
  expect(matchesDate(null, 'today', now)).toBe(false);
});
