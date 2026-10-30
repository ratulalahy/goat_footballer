# Greatest of All Time — methodology

This document fixes the rules before any score is computed. The site asks who is football's greatest
player, measures 21 legends on the same criteria, and argues that the answer is Cristiano Ronaldo. It is
built so that a reader can check every number and change every assumption.

## 1. The question and the lens

"Greatest" has no single statistical definition. The site uses the brief of a forward:

| Criterion family | Question it answers |
|---|---|
| Volume | How many official goals? |
| Big stage | How much of that came in the Champions League and its late rounds? |
| International | What did he do for his country, especially in competitive matches? |
| Longevity | How long did elite output last? |
| Adaptability | Did it travel across leagues, clubs and countries? |
| Completeness | Can he score with either foot and with his head? |

The 16 criteria (five families) are: official goals, goals per game; European Cup/Champions League
goals, titles and final goals; international goals, caps and World Cups with a goal; goals from age 30
and 35, 30-goal club seasons, official matches; leagues where he was top scorer, clubs with 100+ goals,
countries with a league title, and countries whose top league he scored in. Nine are on by default.
Other players lead some of them (Puskás on goals per game, Di Stéfano and Puskás on final goals,
Ibrahimović on leagues scored in), and the page shows it.

**Scope**: creative play (assists, dribbling) and voted awards (the Ballon d'Or) are not scored; on
those, other players rank higher. Team honours enter through the Champions League only.

## 2. Definitions

- **Official match**: competitive senior club matches (league, domestic cups and super cups,
  continental club competitions, Club World Cup) plus full senior internationals, including
  international friendlies (FIFA "A" internationals). Club friendlies, youth/Olympic matches and
  exhibition games are excluded.
- **Goals** exclude penalty-shootout kicks.
- **Champions League** means the group/league phase and knockout rounds (qualifiers excluded),
  and includes the European Cup era for older players.
- **Knockout rounds** (UCL): round of 16, quarter-final, semi-final, final.
- **Competitive international**: World Cup, continental championship (Euro, Copa América),
  their qualifiers, Nations League, Confederations Cup, Finalissima. Friendlies are counted
  separately.
- **Decisive match**: a match whose result (win/draw/loss) would have been worse without the
  player's goals, computed from the final score (shootouts ignored). "Points added" applies the
  3/1/0 scale to that counterfactual.
- **Age**: Ronaldo and Messi use exact age on the day of each match. Other players use season
  totals placed at the season's end, so their age curves are accurate to about one season.

## 3. Composite score (criteria builder)

For the selected criteria `i` with weights `w_i`:

1. Each player `p` gets a criterion score `s_ip = 100 × x_ip / max_p(x_ip)` (ratio to the leader).
   For "lower is better" measures the ratio is inverted (`100 × min / x`).
   An alternative **rank scale** is offered: `s_ip = 100 × (n − rank_ip) / (n − 1)`.
2. Composite `C_p = Σ w_i s_ip / Σ w_i`.
3. **Missing data rule**: a player without a value for a selected criterion is scored on the criteria he
   has and marked † (Pelé, who never played in the European Cup). Nothing is imputed.
4. **Robustness**: 5,000 weight vectors are drawn uniformly from the simplex (Dirichlet, α = 1)
   over the selected criteria; the page reports how often each player ranks first. A result that
   holds under most random weightings does not depend on the chosen weights.

## 4. Peer set

Players most often named in greatest-of-all-time debates, plus the leading scorers of the modern
era with comparable official records. Older players lack some modern measures (Champions League,
Ballon d'Or eligibility before 1995 for non-Europeans), so they appear where their data is
comparable and are marked "not enough data" elsewhere.

## 5. Known limitations

- **Era**: fewer matches per season in earlier decades; no Champions League before 1992.
- **League strength**: Saudi Pro League and MLS are weaker than Europe's top leagues. The site
  reports Europe-only totals alongside career totals.
- **Penalties**: Ronaldo took more. Non-penalty goals are reported, and Messi leads that measure.
- **Opponent strength**: international goals are split by the opponent's FIFA ranking, and club
  goals by the opponent's UEFA club ranking.
- **Age**: Ronaldo is 28 months older. At equal age Messi has scored more; Ronaldo's lead in
  total goals comes from longevity, and the site says so.
- **Performance data** (aerial duels, dribbles) is not available for every match; it is used only
  as supporting evidence and labelled as partial.

## 6. Sources

- messivsronaldo.app match histories (one row per official match, both players), fetched
  2026-10-30; data through 29 Oct 2026 (Ronaldo) and 28 Oct 2026 (Messi).
- English Wikipedia career-statistics tables and honours sections (raw wikitext), fetched 2026-10-30.
- RSSSF, IFFHS, FIFA and UEFA records, news reports for 2025–26 events (see `recent_and_leaderboards.md`).

All derived numbers are produced by the scripts in `research/scripts/`.

## 7. Dashboard methods and references (current version)

The site is a dashboard: a settings rail (comparison group, normalisation, presets, weights) drives every panel.

- **Normalisation** — four methods from the OECD/JRC Handbook on Constructing Composite Indicators (2008):
  distance to a reference (share of the best value), min–max, z-score and ranking. Aggregation is the weighted
  arithmetic mean. Missing values are not imputed; weights are rescaled over the criteria a player has (marked †).
- **Uncertainty analysis** — 5,000 Monte Carlo runs, each with weights drawn uniformly from the simplex (flat
  Dirichlet, as in Rubin's Bayesian bootstrap) and a normalisation method drawn at random, after Saisana, Saltelli
  & Tarantola (2005). Reported: median rank, 5th–95th percentile rank, share of runs ranked first. Seeded RNG.
- **Comparison groups** — all 21; legends (senior debut before 1990, plus Ronaldo); modern era (1990 or later).
- **Age thresholds** — 30 and 35 lie beyond the typical peak age of 25–27 found by Dendir (2016).

References
1. OECD & JRC (2008). Handbook on Constructing Composite Indicators: Methodology and User Guide. OECD Publishing.
2. Saisana, M., Saltelli, A. & Tarantola, S. (2005). Uncertainty and sensitivity analysis techniques as tools for the
   quality assessment of composite indicators. JRSS Series A, 168(2), 307–323. doi:10.1111/j.1467-985X.2005.00350.x
3. Rubin, D. B. (1981). The Bayesian bootstrap. The Annals of Statistics, 9(1), 130–134.
4. Dendir, S. (2016). When do soccer players peak? A note. Journal of Sports Analytics, 2(2).
5. Cleveland, W. S. & McGill, R. (1984). Graphical perception. JASA, 79(387), 531–554.
6. Machado, G. M., Oliveira, M. M. & Fernandes, L. A. F. (2009). A physiologically-based model for simulation of
   color vision deficiency. IEEE TVCG, 15(6), 1291–1298. doi:10.1109/TVCG.2009.113
