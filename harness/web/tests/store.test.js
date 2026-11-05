import { describe, it, expect } from 'bun:test';
import { Store } from '../js/store.js';

describe('Submit Switch Store & Settings', () => {
  it('handles submit switch setting (0 Off, 1 Live)', () => {
    const store = new Store();
    store.setData({
      settings: { 'ctl:submit': 0 },
    });
    expect(store.data.settings['ctl:submit']).toBe(0);

    store.setData({
      settings: { 'ctl:submit': 1 },
    });
    expect(store.data.settings['ctl:submit']).toBe(1);
  });
});
