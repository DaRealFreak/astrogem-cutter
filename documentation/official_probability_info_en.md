# Lost Ark - Probability Information Disclosure: Gem Cutting & Gem Fusion

> Source: https://lostark.game.onstove.com/Probability/%EC%A0%AC%20%EA%B0%80%EA%B3%B5,%20%EC%A0%AC%20%EC%9C%B5%ED%95%A9
> Last updated: 2025-08-20 08:00:00

**General notes:**
- Probabilities for each item are rounded to at least four decimal places beyond the first non-zero digit. Due to rounding, the sum of probabilities may slightly exceed or fall short of 100%.
- You can use the search (Ctrl+F) function to find the probability information you need.

---

## Gem Cutting: Activation (Distribution)

- Probabilities are rounded at the fifth decimal place.
- When activating (distributing) a gem, 1 point is distributed to each of the gem's 4 options, and 2 gem effects are automatically determined according to the rules and probabilities below.

### Gem Options (4 categories)
1. **Willpower Efficiency**
2. **Order/Chaos Points**
3. **First Effect**
4. **Second Effect**

- Duplicate effects cannot appear on the same gem.
- When determining gem effects, the actual probability of each effect appearing is: `listed probability / (100% - sum of listed probabilities of effects excluded by the rules)`.

### Gem Effects by Type

#### Order Gems

| Gem Type | Effect | Probability |
|---|---|---|
| **Order Gem: Stability** | Attack Power | 25.0000% |
| | Additional Damage | 25.0000% |
| | Ally Damage Enhancement | 25.0000% |
| | Brand Power | 25.0000% |
| **Order Gem: Fortitude** | Attack Power | 25.0000% |
| | Boss Damage | 25.0000% |
| | Ally Damage Enhancement | 25.0000% |
| | Ally Attack Enhancement | 25.0000% |
| **Order Gem: Immutability** | Additional Damage | 25.0000% |
| | Boss Damage | 25.0000% |
| | Brand Power | 25.0000% |
| | Ally Attack Enhancement | 25.0000% |

#### Chaos Gems

| Gem Type | Effect | Probability |
|---|---|---|
| **Chaos Gem: Erosion** | Attack Power | 25.0000% |
| | Additional Damage | 25.0000% |
| | Ally Damage Enhancement | 25.0000% |
| | Brand Power | 25.0000% |
| **Chaos Gem: Distortion** | Attack Power | 25.0000% |
| | Boss Damage | 25.0000% |
| | Ally Damage Enhancement | 25.0000% |
| | Ally Attack Enhancement | 25.0000% |
| **Chaos Gem: Collapse** | Additional Damage | 25.0000% |
| | Boss Damage | 25.0000% |
| | Brand Power | 25.0000% |
| | Ally Attack Enhancement | 25.0000% |

---

## Gem Cutting: Processing

- Probabilities are rounded at the fifth decimal place.
- During gem cutting, 4 possibilities appear each turn, automatically determined according to the rules and probabilities below.
- The same possibility cannot appear more than once in the same turn.
- If any exclusion condition is met, that possibility will not appear.
- The actual probability of each possibility appearing is: `listed probability / (100% - sum of listed probabilities of possibilities excluded by the rules)`.
- "View Other Options" (reroll) can be used after at least 1 round of processing.
- When "View Other Options" succeeds, 4 possibilities are re-determined according to the rules above.
  - Possibilities identical to those before the reroll may appear.
- When attempting gem cutting, one of the 4 possibilities is randomly selected (each 25.0000%) and applied.

### Possibilities Table

| Possibility | Probability | Exclusion Condition | Details |
|---|---|---|---|
| Willpower Efficiency +1 | 11.6500% | Willpower Efficiency is 5 | |
| Willpower Efficiency +2 | 4.4000% | Willpower Efficiency is 4 or higher | |
| Willpower Efficiency +3 | 1.7500% | Willpower Efficiency is 3 or higher | |
| Willpower Efficiency +4 | 0.4500% | Willpower Efficiency is 2 or higher | |
| Willpower Efficiency -1 | 3.0000% | Willpower Efficiency is 1 | |
| Order/Chaos Points +1 | 11.6500% | Order/Chaos Points is 5 | For Order Gems, Order Point possibilities appear. For Chaos Gems, Chaos Point possibilities appear. |
| Order/Chaos Points +2 | 4.4000% | Order/Chaos Points is 4 or higher | *(same as above)* |
| Order/Chaos Points +3 | 1.7500% | Order/Chaos Points is 3 or higher | *(same as above)* |
| Order/Chaos Points +4 | 0.4500% | Order/Chaos Points is 2 or higher | *(same as above)* |
| Order/Chaos Points -1 | 3.0000% | Order/Chaos Points is 1 | *(same as above)* |
| First Effect Lv. +1 | 11.6500% | First Effect is Lv. 5 | |
| First Effect Lv. +2 | 4.4000% | First Effect is Lv. 4 or higher | |
| First Effect Lv. +3 | 1.7500% | First Effect is Lv. 3 or higher | |
| First Effect Lv. +4 | 0.4500% | First Effect is Lv. 2 or higher | |
| First Effect Lv. -1 | 3.0000% | First Effect is Lv. 1 | |
| Second Effect Lv. +1 | 11.6500% | Second Effect is Lv. 5 | |
| Second Effect Lv. +2 | 4.4000% | Second Effect is Lv. 4 or higher | |
| Second Effect Lv. +3 | 1.7500% | Second Effect is Lv. 3 or higher | |
| Second Effect Lv. +4 | 0.4500% | Second Effect is Lv. 2 or higher | |
| Second Effect Lv. -1 | 3.0000% | Second Effect is Lv. 1 | |
| Change First Effect | 3.2500% | *(none)* | Uses the same effect probabilities as "Gem Cutting: Activation (Distribution)". The pre-change effect cannot appear. The Second Effect cannot appear. |
| Change Second Effect | 3.2500% | *(none)* | Uses the same effect probabilities as "Gem Cutting: Activation (Distribution)". The pre-change effect cannot appear. The First Effect cannot appear. |
| Processing Cost +100% | 1.7500% | Cost modifier has reached +100%, OR only 1 processing turn remains | From the next turn onward, processing cost modifier increases by +100%. Formula: `Processing Cost = Base Cost x (1 + Cost Modifier%)`. Each gem starts at 0% cost modifier. |
| Processing Cost -100% | 1.7500% | Cost modifier has reached -100%, OR only 1 processing turn remains | From the next turn onward, processing cost modifier decreases by -100%. Formula: `Processing Cost = Base Cost x (1 + Cost Modifier%)`. Each gem starts at 0% cost modifier. |
| Maintain State | 1.7500% | *(none)* | |
| View Other Options +1 | 2.5000% | Only 1 processing turn remains | |
| View Other Options +2 | 0.7500% | Only 1 processing turn remains | |

---

## Gem Cutting: Reset

- A gem being processed can be reset once (1 time only).
  - Gems that have completed processing cannot be reset.
- When resetting, the following are restored to their state immediately after activation (distribution):
  - All 4 gem options (points and effect types)
  - Remaining processing turns
  - View Other Options (reroll) count
  - Processing cost
- When resetting:
  - Possibilities are re-determined according to the processing rules and probabilities.
  - The gem's reset count changes from 1 to 0.

---

## Gem Fusion: Unprocessed Gems

- Probabilities are rounded at the fifth decimal place.
- When fusing unprocessed gems, 3 unprocessed gems are used as materials to produce 1 new unprocessed gem according to the rules and probabilities below.

### Gem Type (Unprocessed Fusion)

The probability of each gem type appearing is: `(number of that gem type used as material / 3) x 100%`.

| Number of That Gem Type | Appearance Probability |
|---|---|
| 1 | 33.3333% |
| 2 | 66.6667% |
| 3 | 100.0000% |

### Tradability (Unprocessed Fusion)

Regardless of the material gems' attributes, the result gem's tradability is determined by the following probabilities:

| Tradability | Probability |
|---|---|
| Tradable | 50.0000% |
| Untradable | 50.0000% |

### Gem Grade (Unprocessed Fusion)

The result gem's grade is determined by the number of each grade among the 3 material gems:

| | **Material Gem Grades** | | | **Result Gem Grade Probability** | |
|---|---|---|---|---|---|
| **Common** | **Rare** | **Epic** | **Common** | **Rare** | **Epic** |
| 3 | 0 | 0 | 85.0000% | 13.5000% | 1.5000% |
| 2 | 1 | 0 | 52.0000% | 44.0000% | 4.0000% |
| 2 | 0 | 1 | 25.0000% | 49.0000% | 26.0000% |
| 1 | 2 | 0 | 19.0000% | 74.5000% | 6.5000% |
| 1 | 1 | 1 | 0.0000% | 71.5000% | 28.5000% |
| 1 | 0 | 2 | 0.0000% | 49.5000% | 50.5000% |
| 0 | 3 | 0 | 0.0000% | 91.0000% | 9.0000% |
| 0 | 2 | 1 | 0.0000% | 69.0000% | 31.0000% |
| 0 | 1 | 2 | 0.0000% | 47.0000% | 53.0000% |
| 0 | 0 | 3 | 0.0000% | 25.0000% | 75.0000% |

---

## Gem Fusion: Processed Gems

- Probabilities are rounded at the fifth decimal place.
- When fusing processed gems, 3 processed gems are used as materials to produce 1 new processed gem according to the rules and probabilities below.

### Gem Type (Processed Fusion)

The probability of each gem type appearing is: `(number of that gem type used as material / 3) x 100%`.

| Number of That Gem Type | Appearance Probability |
|---|---|
| 1 | 33.3333% |
| 2 | 66.6667% |
| 3 | 100.0000% |

### Gem Grade (Processed Fusion)

The result gem's grade is determined by the number of each grade among the 3 material gems:

| | **Material Gem Grades** | | | **Result Gem Grade Probability** | |
|---|---|---|---|---|---|
| **Legendary** | **Relic** | **Ancient** | **Legendary** | **Relic** | **Ancient** |
| 3 | 0 | 0 | 99.0000% | 1.0000% | 0.0000% |
| 2 | 1 | 0 | 73.0000% | 25.0000% | 2.0000% |
| 2 | 0 | 1 | 35.0000% | 40.0000% | 25.0000% |
| 1 | 2 | 0 | 46.0000% | 50.0000% | 4.0000% |
| 1 | 1 | 1 | 8.0000% | 65.0000% | 27.0000% |
| 1 | 0 | 2 | 0.0000% | 50.0000% | 50.0000% |
| 0 | 3 | 0 | 19.0000% | 75.0000% | 6.0000% |
| 0 | 2 | 1 | 0.0000% | 71.0000% | 29.0000% |
| 0 | 1 | 2 | 0.0000% | 48.0000% | 52.0000% |
| 0 | 0 | 3 | 0.0000% | 25.0000% | 75.0000% |

### Gem Points (Processed Fusion)

The result gem's total points are determined by the result gem's grade:

| Gem Points | Legendary | Relic | Ancient |
|---|---|---|---|
| 4 | 1.0000% | - | - |
| 5 | 2.0000% | - | - |
| 6 | 4.0000% | - | - |
| 7 | 7.0000% | - | - |
| 8 | 13.0000% | - | - |
| 9 | 19.0000% | - | - |
| 10 | 22.0000% | - | - |
| 11 | 15.0000% | - | - |
| 12 | 10.0000% | - | - |
| 13 | 4.0000% | - | - |
| 14 | 2.0000% | - | - |
| 15 | 1.0000% | - | - |
| 16 | - | 80.0000% | - |
| 17 | - | 15.0000% | - |
| 18 | - | 5.0000% | - |
| 19 | - | - | 95.0000% |
| 20 | - | - | 5.0000% |

### Gem Point Distribution (Processed Fusion)

The result gem's points are automatically distributed across the 4 gem options according to the following rules:

**Gem Options:**
1. Willpower Efficiency
2. Order/Chaos Points
3. First Effect
4. Second Effect

**Distribution Rules:**
1. Distribute 1 point to each of the 4 gem options.
2. If points remain, distribute 1 point to one of the 4 options at random (each 25.0000%).
   - Options that have reached 5 will no longer receive additional points.
3. Repeat step (2) until all remaining points are distributed.

### Gem Effect Determination (Processed Fusion)

The 2 gem effects are determined using the same method as "Gem Cutting: Activation (Distribution)".
