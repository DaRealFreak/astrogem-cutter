import { describe, it, expect } from 'vitest';
import * as C from '../../src/lib/cv/constants';

describe('vision constants', () => {
  it('matches reference dims and anchor', () => {
    expect([C.REF_WIDTH, C.REF_HEIGHT]).toEqual([1920, 1080]);
    expect(C.ANCHOR_SEARCH_ROI).toEqual([650, 20, 700, 80]);
    expect(C.THRESHOLD_ANCHOR).toBe(0.70);
  });
  it('has 4 option cards and the willpower/chaos ROIs', () => {
    expect(C.OPTION_CARD_POSITIONS).toEqual([[-172,117],[-55,117],[62,117],[179,117]]);
    expect(C.ROI_STAT_WILLPOWER).toEqual([56, 309, 16, 16]);
    expect(C.ROI_STAT_CHAOS).toEqual([56, 427, 16, 16]);
  });
  it('maps gem-type templates to domain and rarity to steps', () => {
    expect(C.GEM_TYPE_TEMPLATE_TO_DOMAIN['order_solidity']).toBe('order_fortitude');
    expect(C.GEM_TYPE_TEMPLATE_TO_DOMAIN['chaos_corrosion']).toBe('chaos_erosion');
    expect(C.RARITY_TOTAL_STEPS['epic']).toBe(9);
    expect(C.RARITY_FROM_TOTAL_STEPS[7]).toBe('rare');
  });
});
