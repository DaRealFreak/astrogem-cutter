import type { DetectionResult } from '../cv/types';

const EFFECT_LABELS: Record<string, string> = {
  attack_power: 'Attack Power',
  additional_damage: 'Additional Damage',
  boss_damage: 'Boss Damage',
  ally_damage: 'Ally Damage',
  brand_power: 'Brand Power',
  ally_attack: 'Ally Attack',
};

function effectLabel(effect: string | null | undefined): string {
  if (!effect) return '';
  return EFFECT_LABELS[effect]
    ?? effect.split('_').map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

/** Human-readable label for an engine offer key (e.g. 'second+1' -> 'Additional Damage +1'). */
export function offerLabel(key: string, det: DetectionResult | null): string {
  const m = key.match(/^([a-z_]+?)([+-]\d+)$/);
  if (m) {
    const kind = m[1];
    const delta = m[2]; // signed, e.g. "+1" / "-1"
    switch (kind) {
      case 'will': return `Willpower ${delta}`;
      case 'chaos': return `Chaos ${delta}`;
      case 'first': return `${effectLabel(det?.firstEffect) || '1st node'} ${delta}`;
      case 'second': return `${effectLabel(det?.secondEffect) || '2nd node'} ${delta}`;
      case 'reroll':
      case 'view': return `View other options (${delta})`;
      case 'cost': return `Cost ${delta}%`;
    }
  }
  switch (key) {
    case 'change_first_effect': return 'Change 1st effect';
    case 'change_second_effect': return 'Change 2nd effect';
    case 'maintain': return 'Maintain';
    default: return key;
  }
}
