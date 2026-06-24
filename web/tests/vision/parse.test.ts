import { describe, it, expect } from 'vitest';
import { parseRerolls, parseDelta, determineOptionKind, sideNodeLevel } from '../../src/lib/cv/recognizer';

describe('parse helpers', () => {
  it('parseRerolls', () => {
    expect(parseRerolls(null)).toBe(0);
    expect(parseRerolls('0_ticket_not_available')).toBe(0);
    expect(parseRerolls('0_ticket_available')).toBe(0);
    expect(parseRerolls('0_ticket_available', true)).toBe(1);
    expect(parseRerolls('2')).toBe(2);
    expect(parseRerolls('1_01')).toBe(1);
    expect(parseRerolls('2', true)).toBe(3);
  });
  it('parseDelta', () => {
    expect(parseDelta('1_line_lvl+3')).toEqual(['lvl', 3]);
    expect(parseDelta('2_line_+2')).toEqual(['points', 2]);
    expect(parseDelta('1_line_-1')).toEqual(['points', -1]);
    expect(parseDelta('cost+100')).toEqual(['cost', null]);
    expect(parseDelta('reroll+1')).toEqual(['reroll', null]);
    expect(parseDelta('1_line_effect_changed')).toEqual(['effect_changed', null]);
    expect(parseDelta('maintained')).toEqual(['maintained', null]);
    expect(parseDelta(null)).toEqual([null, null]);
  });
  it('determineOptionKind', () => {
    expect(determineOptionKind('will', '1_line_lvl+2', 'attack_power', 'ally_damage')).toEqual(['will', 2]);
    expect(determineOptionKind('chaos', '1_line_lvl+1', 'attack_power', 'ally_damage')).toEqual(['chaos', 1]);
    expect(determineOptionKind('attack_power', '1_line_lvl+3', 'attack_power', 'ally_damage')).toEqual(['first', 3]);
    expect(determineOptionKind('ally_damage', '2_line_lvl+1', 'attack_power', 'ally_damage')).toEqual(['second', 1]);
    expect(determineOptionKind('cost', 'cost+100', 'attack_power', 'ally_damage')).toEqual(['cost', null]);
    expect(determineOptionKind('view', 'reroll+1', 'attack_power', 'ally_damage')).toEqual(['view', null]);
  });
  it('sideNodeLevel', () => {
    expect(sideNodeLevel('2_line_lvl3')).toBe(3);
    expect(sideNodeLevel(null)).toBeNull();
  });
});
