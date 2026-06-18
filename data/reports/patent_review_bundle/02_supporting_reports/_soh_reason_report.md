# VERDICTS (adversarial)
## ADVERSARIAL SPAN-CONFOUND CHECK: is very_stale just an artifact of longer observation (median 604 vs 148 days)? Tested via (1) does fcc_change_rate_per_100d separate active vs very_stale WITHIN observation_days bins, and (2) does usage->update-rate survive partial-Spearman / stratified control for observation_days. -> HOLDS
The staleness signal is REAL beyond observation span. The skeptic is right about one mechanical point only: the very_stale LABEL cannot occur at short spans because its definition (FCC flat >=180 trailing days) requires a long enough window, which is why very_stale users are all in the upper obs_days range. That makes the binary label trivially span-correlated. But this is fully defused by switching to the span-robust target fcc_change_rate_per_100d, which is normalized per 100 observed days and therefore not mechanically inflated by span. On that target: (a) very_stale and active are separated by an enormous margin (Cliff d ~0.81-0.98) inside every observation_days bin where both classes coexist, including the longest bin (550-2306d, d=+0.808) - so among equally-long-observed users, very_stale gauges genuinely almost never step FCC (median 0.0-0.43 steps/100d) while active ones do (11-21/100d); and (b) the usage->update-rate relationships are essentially identical raw vs partial-on-obs_days and survive stratification in all four quartiles, while observation_days itself explains only 4% of rate variance (vs 21% for usage) and is actually weakly NEGATIVE (rho -0.136), meaning longer observation does not manufacture higher update rates. The cumulative cycle counters even reverse and strengthen once span is partialled out, exactly as expected if the prior confound was masking a real cycling effect. Conclusion: VERDICT = holds. The gauge-behavior difference (low-cycle / always-AC / shallow-discharge machines re-learn FCC far less, freezing SoH) is a genuine usage-physics effect, not an observation-length artifact. Recommendation: keep reporting against fcc_change_rate_per_100d / flat_pct_of_span rather than the raw very_stale label, and when the binary label is unavoidable, restrict comparisons to the obs>=180d overlap region (n=369) to keep them fair. Data: data/processed/soh_reason_features.csv.
NUMS: Baseline confound confirmed: median observation_days active 148.1, stale 183.7, very_stale 604.3 (~4x). (1) WITHIN-BIN separation of the span-robust rate target is huge: restricting to the obs>=180d overlap region (n=369; 295 active, 55 very_stale) active median fcc_change_rate_per_100d=17.83 vs very_stale=0.289, Cliff d=+0.894, p=6.6e-26. It persists in every span sub-bin: 182-339d d=+0.976 p=1e-08; 342-549d d=+0.934 p=4.7e-08; 550-2306d d=+0.808 p=9.0e-11. In raw obs_days quartiles where very_stale exists at all: Q3 d=+0.975 p=1.3e-10, Q4 d=+0.833 p=2.3e-15. (2) usage->rate is essentially UNchanged by partial control for observation_days: cycles_per_year raw rho +0.603 -> partial +0.603 (p=1e-75); ac_time_ratio -0.394 -> -0.394; ac_event_ratio -0.410 -> -0.405; mean_dod_pct +0.353 -> +0.382; time_ratio_below_20pct +0.337 -> +0.371; mean_pct_remaining -0.301 -> -0.311. Cumulative counters STRENGTHEN once span removed: n_discharge_sessions +0.263 -> +0.541, cycle_count_last +0.212 -> +0.503. Stratified within obs_days quartiles, cycles_per_year->rate holds in all four: Q1 +0.688, Q2 +0.759, Q3 +0.697, Q4 +0.285 (all p<1e-4); ac_time_ratio negative in all (-0.486,-0.442,-0.332,-0.246). Variance decomposition on log(1+rate): observation_days alone R2=0.040; usage features alone R2=0.214; both R2=0.242 (obs adds only +0.028). observation_days vs rate raw rho is only -0.136 (and -0.135 after controlling cycles), i.e. longer span does NOT raise the rate. Structural caveat quantified: very_stale min observation_days=195.9 (p25=345.8), so by construction (>=180 flat trailing days) it cannot appear in Q1/Q2 - the binary label's span dependence is partly mechanical, but 295/661 active users also exceed 180d, so the within-overlap contrast is fair.

## ADVERSARIAL CHECK — USAGE vs HARDWARE CONFOUND: is vendor/device_model over-representation in very_stale EXPLAINED BY usage pattern, or an independent hardware/firmware effect? -> HOLDS
The categorical hardware effect is NOT explained by usage — it is an independent hardware/firmware-linked freeze that survives full usage control. Three independent lines of evidence:

(1) USAGE STILL OPERATES WITHIN A SINGLE MODEL FAMILY. Inside the X1 Carbon/Yoga family (n=223) the usage-physics gradient is intact and strong: cycles_per_year rho=+0.41 (p=1.6e-10, partial vs obs_days +0.40), ac_time_ratio -0.33, ac_event_ratio -0.34, battery_time_ratio +0.33, mean_dod_pct +0.31, time_ratio_below_20pct +0.27 (all p<1e-4) vs fcc_change_rate_per_100d. So the cycling/AC mechanism is real and within-model, but that is separate from the question of whether it EXPLAINS the categorical lift.

(2) THE CATEGORICAL EFFECT SURVIVES USAGE ADJUSTMENT ALMOST UNTOUCHED. OLS on log(1+fcc_change_rate_per_100d): is_LG beta raw -1.843 -> adj -1.687 after adding 6 usage controls = only 8.4% attenuation; is_X1 raw -0.391 -> adj -0.445 = NEGATIVE attenuation (-13.8%, effect slightly strengthens). Adding log(observation_days) too: LG -1.637 (p=2.4e-9), X1 -0.431 (p=3.5e-6). Logistic for very_stale with usage controls: is_LG OR=34.5 (p=1.8e-10), is_X1 OR=5.10 (p=7.8e-7). If usage explained the categories, these coefficients would collapse toward 0; they do not.

(3) SMOKING GUN — X1 IS USED MORE INTENSELY YET UPDATES LESS. X1 machines actually cycle MORE than the rest (cycles_per_year median 76.5 vs 60.2, p=0.001) and have statistically indistinguishable AC-tethering (ac_time_ratio 0.71 vs 0.72, p=0.73), mean_dod (26.0 vs 26.5, p=0.24). Despite heavier cycling they have a LOWER FCC update rate (median 10.7 vs 14.8). Stratifying by cycling tercile, X1 update rate is lower in every stratum (low 3.65 vs 5.76, mid 17.4 vs 18.5, high 33.3 vs 40.5); same within AC terciles (high-AC 4.12 vs 7.32). Usage cannot explain a deficit that persists at matched usage.

LG and X1 are two largely independent hardware signals: only 2/18 LG-cell users are X1 (LG cells sit mostly on T14/L13/P16), and LG usage differs only modestly (slightly higher AC 0.82 vs 0.71, lower cycling 46.7 vs 64 cyc/yr) — far too small to produce a 34x OR. CONCLUSION: the usage-physics mechanism is genuine but ADDITIVE; the LG-cell and X1-generation over-representation is an independent hardware/firmware/aging-linked recalibration failure, not a usage confound.
NUMS: Attenuation of categorical coef after 6 usage controls (log FCC rate OLS): is_LG -1.843->-1.687 (8.4% attenuation); is_X1 -0.391->-0.445 (-13.8%, strengthens). +log(obs_days): LG beta -1.637 p=2.4e-9, X1 -0.431 p=3.5e-6. Logistic very_stale w/ usage controls: LG OR=34.5 p=1.8e-10, X1 OR=5.10 p=7.8e-7. X1 used MORE not less: cycles_per_year 76.5 vs 60.2 (p=0.001), ac_time_ratio 0.71 vs 0.72 (p=0.73, NS), yet FCC update rate 10.7 vs 14.8. Within-X1 (n=223) usage still predicts rate: cycles_per_year rho=+0.41 (partial|obs +0.40), ac_event_ratio -0.34. Stratified X1<rest update rate in all cycling terciles (3.65/17.4/33.3 vs 5.76/18.5/40.5). LG&X1 overlap only 2/18 (independent signals).

## ADVERSARIAL CHECK — LOGGING ARTIFACT: is low fcc_change_rate_per_100d caused by sparse/insufficient sampling (missing FCC steps) rather than true gauge behavior? -> HOLDS
The logging-artifact explanation is firmly REJECTED; low FCC update rate reflects true gauge behavior, not under-sampling.

(1) FCC update rate is uncorrelated with sampling density. Spearman fcc_change_rate_per_100d vs median_sample_gap_min = -0.015 (p=0.68, null) and vs n_samples = +0.042 (p=0.25, null). If sparse sampling caused low rates we would see a strong NEGATIVE rate-vs-gap and POSITIVE rate-vs-n_samples; neither exists. (flat_pct_of_span vs gap is also tiny: rho=-0.096.)

(2) very_stale users are sampled MORE, not less. Median n_samples: very_stale 5089 vs active 1828 (~2.8x MORE, MWU p=3.6e-07). Median sample gap is identical across all three groups (30.0 min; MWU very_stale vs active p=0.27, NS). So the frozen group has the most evidence, not the least.

(3) The logger runs a near-fixed ~30-min cadence fleet-wide: median gap 30 min, IQR 30-30, max 99 min; 91.9% of all users (98.2% of very_stale) sit in [25,35] min; ZERO users have median gap >120 min. There is no sparsely-sampled subpopulation that could be hiding FCC steps.

(4) The flat tails are densely covered. Every very_stale flat tail (>=180d by definition, min observed 181.8d) is sampled at ~30 min, i.e. >=~8,700 samples; estimated samples inside the flat tail: median ~19,094, min 8,726, max 57,518. Tens of thousands of readings all report an unchanging integer FCC — the gauge genuinely is not stepping.

(5) Controlling for observation_days removes any residual concern: partial Spearman rate vs sample_gap | obs_days = +0.011 (p=0.77, null); rate vs n_samples | obs_days = +0.245 (p=1e-11) — after span control MORE samples weakly predicts a HIGHER update rate, the OPPOSITE direction from an under-sampling artifact, and very_stale users already have more samples, so sampling cannot explain their depressed rate.

Conclusion: very_stale users are observed longer AND sampled more densely (≈3x more samples, same 30-min cadence, ≥8.7k confirming readings in each flat tail), yet their integer FCC never steps. Low fcc_change_rate_per_100d is real fuel-gauge inactivity, not a logging/sampling artifact.
NUMS: rate vs median_sample_gap_min rho=-0.015 (p=0.68); rate vs n_samples rho=+0.042 (p=0.25); rate vs observation_days rho=-0.136. n_samples median: very_stale 5089 vs active 1828 (MWU p=3.6e-07). median_sample_gap_min: 30.0 for all 3 groups (very_stale vs active p=0.27 NS). Sample gap: median 30, IQR 30-30, max 99 min; 0/752 users >120 min; 91.9% in [25,35] min (very_stale 98.2%). Est. samples in >=180d flat tail (very_stale): median 19094, min 8726, max 57518. Partial | obs_days: rate vs gap +0.011 (p=0.77), rate vs n_samples +0.245 (p=1e-11).

# SYNTHESIS REPORT
# なぜ SoH の更新が止まるのか — 検証済みエビデンスによる結論

データ: `data/processed/soh_reason_features.csv`（752ユーザー、active 661 / stale 36 / very_stale 55、very_stale 基準率 7.3%）。
SoH = FCC*100/DesignCapacity であり、DesignCapacity はユーザーごとに一定。よって SoH は整数 FCC がステップしたときのみ更新される。「SoH が止まる」=「燃料計（fuel gauge）が FCC を再学習しなくなる」と同義。

すべての結論は span-robust 指標 `fcc_change_rate_per_100d`（観測100日あたりの FCC ステップ数）で検証し、観測長の交絡を除去した。本コンソールで再計算して数値を確認済み。

## 中核となる事実（検証済み）
- active と very_stale の FCC 更新率は桁違い: 中央値 active **17.6** vs stale **0.63** vs very_stale **0.29**（/100日）。
- 観測長の交絡は実在: 観測日数中央値 active 148 / stale 184 / very_stale 604（約4倍）。**ただし交絡は無害化できる**: 観測 >=180日 の重なり領域（n=369、active 295・very_stale 55）に限定しても active 17.83 vs very_stale 0.289、**Cliff d=0.894, p=6.5e-26**。つまり「同じくらい長く観測された」ユーザー同士でも very_stale はほぼ FCC をステップしない。
- ロギング由来ではない: ロガーは全機ほぼ固定 ~30分間隔（3群とも中央値30分）。very_stale はサンプル数がむしろ約2.8倍多い（5089 vs 1828）。サンプル密度と更新率は無相関（rho=-0.015, p=0.68）。FCC 不更新は real な計測器の挙動。

## なぜ止まるのか — 二つの独立した原因（加算的）

### 原因1: 使用パターン（連続指標で強く確認）
燃料計は実際の充放電サイクル中に主に FCC を再学習する。常時AC接続・低サイクル・浅い放電の機械は再較正の機会が乏しく、SoH が凍結する。`fcc_change_rate_per_100d` との Spearman（観測日数を partial control しても不変）:
- **cycles_per_year +0.603**（partial +0.599）— 最強。サイクルが多いほど更新。
- ac_event_ratio -0.410 / ac_time_ratio -0.394 — AC 接続が多いほど更新しない。
- battery_time_ratio +0.394、mean_dod_pct +0.353（partial +0.383）、time_ratio_below_20pct +0.337 — 深い・低残量の放電ほど更新。
- mean_pct_remaining -0.301 — 高残量で保持するほど更新しない。
- 累積カウンタ（n_discharge_sessions, cycle_count_last）は観測長を partial out すると +0.26→+0.55 と**強化**（交絡で隠れていた真のサイクル効果）。
- null: median_drain_pct_per_hr +0.063（p=0.09）。放電「速度」は無関係、効くのは放電の「深さ/頻度」。

### 原因2: ハードウェア/ファームウェア世代（使用パターンでは説明できない独立効果）
- **LG セル（LGC+LGES, n=18）の 55.6% が very_stale**（OR≈21）。全 very_stale の **10/55** がわずか18ユーザーの LG セルから出る。LGC 単独 75%(6/8, OR=42.6), LGES 40%(4/10, OR=9.0)。
- **旧世代 ThinkPad X1 Carbon/Yoga（Gen <=11, n=95）の 30.5% が very_stale**（全 very_stale の **29/55**）。一方 **X1 Gen >=12（n=126）はわずか 1.6%**。Gen11→12 で鋭く切り替わる: 更新率中央値 Gen6-11 は 0.43-1.74 に対し Gen12-14 は 22-29。これはファームウェア/世代スイッチの強い示唆。
- LG と X1 はほぼ独立（LGセル18人のうち X1 はわずか2人; LG は主に T14/L13/P16 上）。
- **ハードウェア効果は使用調整後もほぼ無傷**: log(1+rate) の OLS で is_LG 係数 -1.843→-1.69（8%減衰のみ）、is_X1 -0.391→-0.43（むしろ強化, p=3e-6）。
- **決定的証拠（X1）**: X1 は他機よりむしろ多くサイクル（cycles_per_year 76.5 vs 60.2）、AC 接続は同等（0.71 vs 0.72）にもかかわらず更新率は低い（10.7 vs 14.8）。使用で説明できない欠損。

## 棄却した主張
- 「very_stale は単に観測が長いだけの人工物」→ 棄却。重なり領域で Cliff d=0.894。very_stale ラベル自体は定義上（>=180日フラット）長スパンを要するので機械的に span 相関するが、span-robust 指標では完全に分離する。
- 「低更新率はサンプル不足のせい」→ 棄却。density 無相関、very_stale はむしろ高密度。
- batt_vendor は device_model 世代の proxy という主張は一部正しいが、LG セルは X1 と独立にリスクを持つため、独立効果として扱う。

## バイナリラベルでの注意
要求された active-vs-very_stale の中央値分割では使用系特徴の効果は小さく多くが非有意（cycles_per_month d=+0.14 p=0.08 等）。これはラベル自体が観測長に依存するため。報告は `fcc_change_rate_per_100d` ベースで行うべき。

## 全体トレンドの要約
SoH 凍結は二つの独立した経路の加算: (1) 充放電サイクルが乏しい使用（常時AC・低サイクル・浅放電）で燃料計が再較正されない、(2) 特定ハードウェア — LG セルパックと旧世代 X1 Carbon/Yoga（Gen<=11）— の世代/ファームウェア的較正失敗。very_stale 55人の内訳は概ね LG セル10 + 旧世代X1 27 + 純粋な使用要因（AC固定/浅放電）8 + 残余10 で、ハードウェア起因が支配的。

# RANKED REASONS
[HIGH] 旧世代 ThinkPad X1 Carbon/Yoga（Gen <=11）のファームウェア/世代由来の較正失敗。X1 Gen<=11 (n=95) の 30.5% が very_stale で全 very_stale の 29/55 を占める一方、Gen>=12 (n=126) は 1.6% のみ。Gen11→12 で更新率中央値が 0.43-1.74 から 22-29 へ急変。使用パターン調整後も is_X1 係数は減衰せず（-0.39→-0.43, p=3e-6）、X1 はむしろ多くサイクルし(76.5 vs 60.2/yr)AC同等(0.71 vs 0.72)なのに更新率が低い(10.7 vs 14.8)＝使用で説明不能。
   ev: X1 Gen<=11 n=95 vs_rate=0.305 (29 vstale); Gen>=12 n=126 vs_rate=0.016. fcc_rate median Gen6-11: 0.43-1.74, Gen12-14: 22.05-28.56. OLS log(1+rate): is_X1 raw -0.391 -> adj -0.429 (p=3.0e-6). X1 cycles_per_year 76.5 vs 60.2, ac_time_ratio 0.706 vs 0.718, fcc_rate 10.68 vs 14.82.
[HIGH] LG 製セルパック（LGC/LGES）のハードウェア由来較正失敗。わずか18ユーザー（フリートの約2%）の 55.6% が very_stale で、全 very_stale の 10/55 を供給。X1 とほぼ独立（重複2/18、LG セルは主に T14系）。使用調整後も係数の減衰は8%のみ。
   ev: LG combined n=18 rate=0.556 (LGC 6/8=0.75 OR=42.6 p=2.9e-6; LGES 4/10=0.40 OR=9.0 p=3.9e-3). share 10/55 of very_stale. OLS is_LG raw -1.843 -> adj -1.693 (p=3.8e-10, 8% attenuation). LG-cell users that are X1 = 2.
[HIGH] 低サイクル使用（燃料計が再学習されない）。cycles_per_year が FCC 更新率の最強予測子で、観測日数を partial control しても不変。累積カウンタは span を除くと強化され真のサイクル効果が現れる。
   ev: cycles_per_year rho=+0.603 (p=1.0e-75), partial|obs +0.599. n_discharge_sessions raw +0.263 -> partial|obs +0.552. cycle_count_last +0.212 -> +0.529.
[HIGH] 常時AC接続（バッテリーが充放電せず再較正の機会が乏しい）。AC 比率が高いほど FCC 更新率が低い。partial control 後も不変。
   ev: ac_event_ratio rho=-0.410, ac_time_ratio -0.394 (partial|obs -0.392), time_ratio_full_on_ac -0.235, battery_time_ratio +0.394 (all p<1e-10).
[HIGH] 浅い放電・高残量保持（深い放電が無いと FCC 再学習が起きにくい）。放電の深さ/頻度は効くが、放電速度は効かない。
   ev: mean_dod_pct rho=+0.353 (partial +0.383), time_ratio_below_20pct +0.337 (partial +0.368), mean_pct_remaining -0.301. NULL: median_drain_pct_per_hr +0.063 (p=0.086).
[HIGH] 観測長の交絡で very_stale ラベルが膨らむという仮説 — 部分的に機械的だが span-robust 指標で無害化される。原因ではなく分析上の注意点として扱う。
   ev: obs_days median active 148 / very_stale 604 (4x). しかし obs>=180d 重なり(n=369): active fcc_rate 17.83 vs very_stale 0.289, Cliff d=0.894 p=6.5e-26. usage->rate は raw≒partial で不変。
[HIGH] スパースサンプリングで FCC ステップを見落としているという仮説 — 棄却。ロギング由来ではない。
   ev: rate vs sample_gap rho=-0.015 (p=0.68), vs n_samples +0.042. very_stale は n_samples 5089 vs active 1828（約2.8倍多い）、gap は3群とも中央値30分。

# PROPOSED SUB-LABELS
* HW_LG_cell_pack (n~13 (of which 10 very_stale))
   rule: soh_update_status.isin(['stale','very_stale']) & batt_vendor.isin(['LGC','LGES'])
* HW_X1_old_gen (ThinkPad X1 Carbon/Yoga Gen<=11, firmware/generation-linked freeze) (n~50 (of which 27 very_stale). 注: 'X1 Yoga 3rd/4th' 等の非'Gen N'表記は旧世代として含めると合計約53)
   rule: soh_update_status.isin(['stale','very_stale']) & ~batt_vendor.isin(['LGC','LGES']) & device_model.str.contains('X1 Carbon|X1 Yoga', case=False, na=False) & (device_model.str.extract(r'Gen (\d+)')[0].astype('float') <= 11)
* USE_AC_bound_no_cycling (always-on-AC low-cycle, non-HW) (n~5 (of which 3 very_stale). 閾値 cycles_per_year<コホートp25=30.27)
   rule: soh_update_status.isin(['stale','very_stale']) & ~batt_vendor.isin(['LGC','LGES']) & ~(device_model.str.contains('X1 Carbon|X1 Yoga', case=False, na=False) & (device_model.str.extract(r'Gen (\d+)')[0].astype('float') <= 11)) & (ac_time_ratio >= 0.80) & (cycles_per_year < 30.27)
* USE_shallow_discharge_topup (low-DoD high-residual desk machine, non-HW/non-AC) (n~7 (of which 5 very_stale). 閾値 = フリート中央値 mean_dod_pct<26.27, mean_pct_remaining>89.83)
   rule: soh_update_status.isin(['stale','very_stale']) & ~batt_vendor.isin(['LGC','LGES']) & ~(device_model.str.contains('X1 Carbon|X1 Yoga', case=False, na=False) & (device_model.str.extract(r'Gen (\d+)')[0].astype('float') <= 11)) & ~((ac_time_ratio >= 0.80) & (cycles_per_year < 30.27)) & (mean_dod_pct < 26.27) & (mean_pct_remaining > 89.83)
* RESIDUAL_unexplained (normal usage + non-flagged hardware, yet frozen — likely other firmware/gauge-policy) (n~16 (of which 10 very_stale). median profile: ac 0.65, cycles_per_year 47, dod 33, rem 83, vendor mostly SMP — 通常の使用なのに凍結、別経路（ファームウェア/計測器ポリシー）を示唆)
   rule: soh_update_status.isin(['stale','very_stale']) & ~( batt_vendor.isin(['LGC','LGES']) | (device_model.str.contains('X1 Carbon|X1 Yoga', case=False, na=False) & (device_model.str.extract(r'Gen (\d+)')[0].astype('float') <= 11)) | ((ac_time_ratio >= 0.80) & (cycles_per_year < 30.27)) | ((mean_dod_pct < 26.27) & (mean_pct_remaining > 89.83)) )