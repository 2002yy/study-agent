# Firefly default lesson — data-depth audit

Status: implementation input for PR #165. This document does not change the 10-card structure. It freezes the minimum numeric depth expected in expanded cards and the same-page core-character archive.

## Authority and version rule

- Firefly uses the post-4.2 kit. Pre-4.2 data must not be mixed into visible copy.
- In particular, old Firefly traces `55% off-element toughness`, `200%/360% thresholds`, and `35%/50% self Super Break` are obsolete for this lesson.
- Post-4.2 Firefly uses: A2 +25% Break Effect plus up to three 10% countdown delays on Weakness Break; A4 thresholds 150%/300% and 100%/150% Super Break; enhanced Skill implants Fire Weakness on the main target and adjacent targets; E2 resets its trigger eligibility each SAM turn.
- Visible toughness numbers use the lesson's 10/20/30 convention. Sources that expose 30/60/90 are divided by 3 before display.
- Default numeric view shows normal practical caps: Basic Lv.6; Skill/Ultimate/Talent Lv.10. E3/E5 can expose Lv.12 deltas. Full Lv.1–15 growth tables belong behind a deeper disclosure, not in the default expanded card.
- `Complete-data scope` includes the character's Technique and exact core Light Cone values used by this lesson. It does not mean every Light Cone in the game.

## Firefly — practical max-rank data

### Basic / enhanced Basic
- Basic: 100% ATK, 20 Energy, 10 toughness, +1 SP.
- Enhanced Basic: 200% ATK, restores 20% Max HP, 15 toughness, 0 Energy.

### Skill / enhanced Skill
- Skill Lv.10: 200% ATK, costs 40% Max HP, restores 60% Max Energy (=144 of 240), advances next action 25%, 20 toughness, costs 1 SP.
- Enhanced Skill Lv.10: main target `(0.2 × Break Effect + 200%) ATK`; adjacent `0.1 × Break Effect + 100% ATK`; Break Effect term caps at 360%; restores 25% Max HP; implants Fire Weakness for 2 turns on the main target and adjacent targets after the 4.2 update; toughness 30 main / 15 adjacent.

### Ultimate Lv.10
- Energy cost 240; self action advance 100%.
- SPD +60.
- Enhanced attacks Weakness Break Efficiency +50%.
- Targets hit by SAM take +20% Break DMG for that attack.
- Complete Combustion countdown has fixed SPD 70.

### Talent Lv.10
- Max DMG reduction 40%; in Complete Combustion stays at the maximum.
- Effect RES +30% during Complete Combustion.
- Battle start: Energy is raised to 50% if below it.
- Reaching full Energy cleanses all dispellable debuffs.

### Technique
- 5 s aerial movement.
- At each wave start, applies Fire Weakness for 2 turns.
- 200% ATK AoE and 20 toughness.

### Major traces — post-4.2
- A2: during Complete Combustion, Break Effect +25%; when enhanced Basic/Skill causes Weakness Break, countdown action is delayed 10%; up to 3 triggers per Complete Combustion.
- A4: at 150% / 300% Break Effect, attacks against Weakness Broken enemies convert toughness into 100% / 150% self Super Break.
- A6: above 1800 ATK, every additional 10 ATK grants 0.8% Break Effect.

### Eidolons
- E1: enhanced Skill ignores 15% DEF and costs no SP.
- E2: in Complete Combustion, enhanced Basic/Skill that kills or Weakness Breaks grants 1 Extra Turn; triggerable once per SAM turn and eligibility resets at the start of SAM's turn.
- E3: Skill +2, Basic +1.
- E4: Complete Combustion Effect RES +50%.
- E5: Ultimate +2, Talent +2.
- E6: Fire RES PEN +20% in Complete Combustion; enhanced attacks gain another +50% Weakness Break Efficiency.

### Core Light Cones shown by the lesson
- Whereabouts Should Dreams Rest S1: Break Effect +60%; after the wearer deals Break DMG, target receives +24% Break DMG from that wearer and SPD -20% for 2 turns.
- On the Fall of an Aeon S5: each attack grants +16% ATK, max 4 stacks; after Weakness Break, DMG +24% for 2 turns. The DMG buff itself does not enter Super Break, while the ATK can feed Firefly A6.
- Indelible Promise S5: Break Effect +56%; Ultimate grants CRIT Rate +30% for 2 turns. CRIT does not enter Super Break.

## The Dahlia — practical max-rank data

### Basic
- Lv.6: 100% ATK, 20 Energy, 10 toughness, +1 SP.

### Skill Lv.10
- 160% ATK to main and adjacent targets.
- 30 Energy, 10 toughness per hit in the lesson scale, costs 1 SP.
- Zone lasts 3 turns.
- Team Weakness Break Efficiency +50% while Zone is active.
- Toughness reduction dealt to enemies that are not Weakness Broken can also produce Super Break DMG.

### Ultimate Lv.10
- 130 Energy cost, 20 AoE toughness.
- 300% ATK Fire DMG distributed among all enemies.
- `Wilt` lasts 4 turns.
- DEF -18%.
- Adds all Dance Partner element Weaknesses.

### Talent Lv.10
- On entering battle: restores 35 Energy and assigns herself plus another ally as Dance Partners.
- Dance Partner attacks against Weakness Broken enemies convert toughness into 60% Super Break.
- After the other Dance Partner attacks, Dahlia launches a 5-hit follow-up; each hit is 30% ATK, restores 2 Energy for the follow-up as recorded by the lesson data source, and each hit has 3 toughness in the lesson scale.
- Each follow-up hit against a Weakness Broken target converts its toughness into 200% Super Break.
- Follow-up trigger: at most once per turn.

### Technique
- Creates a special field for 20 s; enemies inside do not actively attack.
- Entering battle inside the field immediately opens the Skill Zone.
- Opening toughness reduction against already Weakness Broken enemies can convert into 60% Super Break; only one same-type field can exist.

### Major traces
- A2: other allies gain `24% of Dahlia's Break Effect + 50%` Break Effect for 1 turn on battle entry; teammate heal/shield can retrigger it for 3 turns, at most once in a turn.
- A4: restores 1 SP for every 2 Talent follow-ups.
- A6: ally weakness implant gives Dahlia +30% SPD for 2 turns; Fire-character weakness implant also deals 20 fixed Fire toughness and restores 10% Max Energy, with this Energy effect capped at 50% Max Energy.

### Eidolons
- E1: Talent Super Break multiplier applies to all allies; Dance Partner gets an additional +40 percentage points; after Dance Partner attacks, deals fixed toughness equal to 25% of target Max Toughness, minimum 10 and maximum 300, once per target until kill resets it.
- E2: all enemies All-Type RES -20%; newly entering enemies immediately receive Wilt for 3 turns.
- E3: Ultimate +2, Basic +1.
- E4: Talent follow-up gains 5 extra hits; each hit makes target DMG taken +12% for 2 turns.
- E5: Skill +2, Talent +2.
- E6: Dance Partner Break Effect +150%; Talent follow-up advances all Dance Partners by 20%.

### Core Light Cones shown by the lesson
- Never Forget Her Flame S1: Break Effect +60%; at battle entry, wearer and another opening ally deal +32% Break DMG; adding a Weakness restores 1 SP, once between Ultimates, and Ultimate resets the trigger.
- Resolution Shines As Pearls of Sweat S5: 100% base chance to apply Ensnared to a target not already Ensnared; DEF -16% for 1 turn.
- Before the Tutorial Mission Starts S5: Effect Hit Rate +40%; attacking a DEF-reduced enemy restores 8 Energy.

## Fugue — practical max-rank data

### Basic / enhanced Basic
- Basic Lv.6: 100% ATK, 20 Energy, 10 toughness.
- Enhanced Basic: 100% ATK main / 50% ATK adjacent, 20 Energy, 10 main / 5 adjacent toughness.

### Skill Lv.10
- 30 Energy, costs 1 SP, lasts 3 turns.
- Foxian Prayer target Break Effect +30%.
- Can reduce toughness without matching Weakness at 50% of original efficiency; does not stack with other ignore-Weakness toughness effects.
- Each attack from the Foxian Prayer target has 100% base chance to reduce attacked enemies' DEF by 18% for 2 turns.

### Ultimate Lv.10
- 130 Energy cost, 200% ATK AoE.
- 20 AoE toughness and ignores Weakness type for toughness reduction.

### Talent Lv.10
- Adds Exo-Toughness equal to 40% of original Max Toughness.
- Attacks against Weakness Broken enemies convert toughness into 100% Super Break.

### Major traces
- A2: after an ally causes Weakness Break, additionally delays the enemy action by 15%.
- A4: Fugue Break Effect +30%; first Skill use immediately refunds 1 SP.
- A6: when an enemy is Weakness Broken, allies other than Fugue gain +6% Break Effect; if Fugue has at least 220% Break Effect, adds another +12%; lasts 2 turns and stacks up to 2 times.

### Technique
- 10 s field stun.
- On entering battle against a stunned target, Fugue advances 40% and has 100% base chance to apply the same DEF reduction as her Skill for 2 turns.

### Eidolons
- E1: Foxian Prayer target Weakness Break Efficiency +50%.
- E2: each enemy Weakness Break restores 3 Energy to Fugue; Ultimate advances all allies 24%.
- E3: Skill +2, Basic +1.
- E4: Foxian Prayer target Break DMG +20%.
- E5: Ultimate +2, Talent +2.
- E6: Fugue Weakness Break Efficiency +50%; while in Torrid Scorch, Foxian Prayer applies to all allies.

### Core Light Cones shown by the lesson
- Long Road Leads Home S1: Break Effect +60%; when an enemy is Weakness Broken, 100% base chance to make it take +18% Break DMG for 2 turns, stacking up to 2 times.
- Solitary Healing S5: Break Effect +40%; Ultimate increases the wearer's DoT by 48% for 2 turns; defeating an enemy carrying the wearer's DoT restores 6 Energy.
- Before the Tutorial Mission Starts S5: Effect Hit Rate +40%; attacking a DEF-reduced enemy restores 8 Energy.
- Resolution Shines As Pearls of Sweat S5: 100% base chance to apply Ensnared; DEF -16% for 1 turn.

## Lingsha — practical max-rank data

### Basic
- Lv.6: 100% ATK, 20 Energy, 10 toughness.
- Major trace adds another 10 Energy when using Basic.

### Skill Lv.10
- 80% ATK AoE, 30 Energy, 10 AoE toughness, costs 1 SP.
- Team heal: 14% ATK + 420.
- Fuyuan action advance 20%.

### Ultimate Lv.10
- 110 Energy cost, 150% ATK AoE, 20 AoE toughness.
- `Befog` makes enemies take +25% Break DMG for 2 turns.
- Team heal: 12% ATK + 360.
- Fuyuan action advance 100%.

### Talent Lv.10
- Fuyuan starts at SPD 90 with 3 actions; maximum stored actions 5.
- Each Fuyuan action deals 75% ATK AoE plus one additional 75% ATK hit to a random target; all enemies take 10 toughness and the selected random target takes another 10 in the lesson scale.
- Cleanses 1 debuff from all allies.
- Team heal: 12% ATK + 360.
- Skill adds 3 Fuyuan actions while it is present.

### Technique
- At the start of the next battle, immediately summons Fuyuan and applies Befog to all enemies for 2 turns.

### Major traces
- A2: converts Break Effect into ATK and Outgoing Healing at 25% / 10% of Break Effect, capped at +50% ATK / +20% healing.
- A4: Basic additionally restores 10 Energy.
- A6: if an ally falls to 60% HP or lower while Fuyuan is present, immediately triggers the Talent follow-up without consuming an action count; 2-turn cooldown.

### Eidolons
- E1: Lingsha Weakness Break Efficiency +50%; when an enemy is Weakness Broken, DEF -20%.
- E2: Ultimate grants all allies +40% Break Effect for 3 turns.
- E3: Ultimate +2, Talent +2.
- E4: Fuyuan action additionally heals the lowest-HP ally for 40% of Lingsha ATK.
- E5: Skill +2, Basic +1.
- E6: while Fuyuan is present, all enemies All-Type RES -20%; Fuyuan attacks add 4 random hits, each 50% ATK and 5 toughness.

### Core Light Cones shown by the lesson
- Scent Alone Stays True S1: Break Effect +60%; after Ultimate attacks an enemy, target takes +10% DMG for 2 turns; if the wearer's Break Effect is at least 150%, another +8% is added.
- Quid Pro Quo S5: at the wearer's turn start, randomly restores 16 Energy to another ally below 50% Energy.
- Post-Op Conversation S5: Energy Regeneration Rate +16%; Outgoing Healing when using Ultimate +24%.
- What Is Real? S5: Break Effect +48%; after Basic Attack, wearer heals 4% Max HP + 800.

## Gallagher — practical max-rank data

### Basic / enhanced Basic
- Basic Lv.6: 100% ATK, 20 Energy, 10 toughness.
- Enhanced Basic Lv.6: 250% ATK, 20 Energy, 30 toughness; target ATK -15% for 2 turns.

### Skill Lv.10
- Flat heal 1600 HP.
- 30 Energy, costs 1 SP.

### Ultimate Lv.10
- 110 Energy cost, 150% ATK AoE, 20 AoE toughness.
- Applies Besotted for 2 turns.
- Enhances the next Basic to Nectar Blitz.

### Talent Lv.10
- Besotted enemies take +12% Break DMG.
- When an ally attacks a Besotted target, that attacker heals 640 HP.

### Major traces
- A2: Outgoing Healing increases by 50% of Gallagher's Break Effect, up to +75% Outgoing Healing.
- A4: after Ultimate, Gallagher action advances 100%.
- A6: enhanced Basic against a Besotted enemy applies the Talent heal to all allies for that attack.

### Technique
- On entering battle after attacking: applies Besotted for 2 turns, deals 50% ATK AoE and 20 AoE toughness.

### Eidolons
- E1: battle entry restores 20 Energy; Effect RES +50%.
- E2: Skill cleanses 1 debuff and gives target Effect RES +30% for 2 turns.
- E3: Skill +2, Basic +1.
- E4: Ultimate's Besotted duration +1 turn.
- E5: Ultimate +2, Talent +2.
- E6: Break Effect +20%; Weakness Break Efficiency +20%.

### Core Light Cones shown by the lesson
- What Is Real? S5: Break Effect +48%; after Basic Attack, wearer heals 4% Max HP + 800.
- Quid Pro Quo S5: at the wearer's turn start, randomly restores 16 Energy to another ally below 50% Energy.
- Post-Op Conversation S5: Energy Regeneration Rate +16%; Outgoing Healing on Ultimate +24%. Gallagher's Ultimate does not heal, so the relevant part is the Energy Regeneration Rate.

## UI consequence

Expanded analytical cards keep mechanism and decision context. The same-page numeric archive exposes character-level exact data without turning every analytical card into a database table.

Each core-character tab must include a Technique row, three major traces, six Eidolons, and a `Core Light Cones` disclosure with explicit S1/S5 values. The Light Cone list is restricted to options that this lesson actually recommends or compares.

On narrow screens, character-data tables keep an internal minimum width and scroll horizontally inside their wrapper. The page itself must not gain horizontal overflow.

The route-support characters (Harmony Trailblazer, Asta, Ruan Mei) stay at role-level in the route card unless they receive their own detail tab; do not pretend their exact skill data is covered if it is not shown.
