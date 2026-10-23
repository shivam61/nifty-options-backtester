# Volatility term structure, VIX-curve and regime signals for timing/sizing short-vol (and implications for a Nifty options-selling backtester)

## Access report (read this first)

**Full text was not read for any source in this note.** The research sandbox's egress proxy returned policy 403 for these hosts, so full texts could not be fetched (per /root/.ccr/README.md I did not try to route around them): arxiv.org, export.arxiv.org, ideas.repec.org, econpapers.repec.org, api.semanticscholar.org, api.crossref.org, core.ac.uk, alphaxiv.org, huggingface.co, nber.org, efmaefm.org, cxoadvisory.com, goodreads.com, ar5iv. The WebFetch tool also failed DNS (ENOTFOUND) on arxiv.org, ar5iv, alphaxiv, ideas.repec.org, efmaefm.org and goodreads.com. Only WebSearch worked, and it returns a model-written digest of result pages, not the pages. Every number below is therefore from a **search-engine digest of the abstract or a secondary summary (CXO Advisory, Quantpedia, ResearchGate snippets)**, and the digests themselves flagged some figures as garbled. Anything marked [UNVERIFIED] must be checked against the primary PDF before use. Nothing was filled in from memory; unanswered items are listed under Gaps.

Source register (all abstract/secondary only):
| Paper | Authors / year / venue | URL | Read |
|---|---|---|---|
| The VIX Futures Basis: Evidence and Trading Strategies | Simon & Campasano, 2012 EFMA draft; published J. Derivatives 2014 (venue/year per the task brief, not confirmed by my sources) | https://www.efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2013-Reading/papers/EFMA2013_0164_fullpaper.pdf | search digest only |
| Explaining the negative returns to volatility claims: An equilibrium approach | Eraker & Wu, 2017, J. Financial Economics 125, 72-98 | https://academicnewsletter.sufe.edu.cn/info/356257 | digest only |
| Volatility Exchange-Traded Notes: Curse or Cure? | Alexander & Korovilas, May 2012 version | https://www.cxoadvisory.com/volatility-effects/enhanced-vix-futures-etns | CXO summary via digest |
| Trading volatility: at what cost? (VIX ETPs) | Whaley, May 2013 draft; JPM | https://news.vanderbilt.edu/2013/10/18/volatility-etps/ | press/secondary digest |
| Risk Premia and the VIX Term Structure | Travis Johnson, 2015 (JFQA per common citation, not confirmed here) | https://www.cxoadvisory.com/volatility-effects/vix-term-structure-slope-and-variance-asset-future-returns/ | CXO summary via digest |
| The Expected Return of Fear (Cheng); Huang & Shaliastovich 2014 (VVIX) | as cited by CXO | https://www.cxoadvisory.com/volatility-effects/timing-vix-futures-with-the-futures-spot-ratio/ ; https://www.cxoadvisory.com/volatility-effects/expected-volatility-of-stock-market-volatility-as-a-predictor/ | CXO summary via digest |
| The Volatility Edge: A Dual Approach for VIX ETNs Trading | Zarattini, Aziz, Mele; SFI WP 25-91, Oct 2025 | https://www.sfi.ch/de/publications/n-25-91-the-volatility-edge-a-dual-approach-for-vix-etns-trading | abstract-level digest |
| Sizing the Risk: Kelly, VIX, and Hybrid Approaches in Put-Writing on Index Options | Maciej Wysocki (Univ. of Warsaw), arXiv 2508.16598, 9 Aug 2025, q-fin.PM; a ScienceDirect/ACM listing in Knowledge-Based Systems vol 348 appeared in search results but a digest could not confirm it | https://arxiv.org/abs/2508.16598 | **abstract + ResearchGate snippet only; full text NOT reached** |
| Measuring and trading volatility in the US stock market: a regime switching approach | Dapena, Serur, Siri, CEMA WP 659, 2018 | https://ucema.edu.ar/documento-trabajo/measuring-and-trading-volatility-us-stock-market-regime-switching-approach | abstract digest |

---

## Q1. Roll-yield and term-structure evidence for short VIX futures / short-vol strategies

### Takeaway
Long VIX futures/ETPs lose heavily on average because the curve is usually in contango and futures overprice expected VIX; this is a priced risk premium, so shorting the curve earned a premium historically. But simple static short-vol had small Sharpe ratios and extreme tail losses, and all the tradable-timing evidence is short-sample, in-sample and mostly gross of costs.

### Cited Findings
- Eraker & Wu (JFE 2017): constant-maturity 1-month VIX futures portfolio "loses about 30% per year over our sample period (2006-2013)"; large negative return premia also for VIX ETNs and variance swaps; explained by a dynamic equilibrium model. Abstract-level only. — [Eraker & Wu digest](https://academicnewsletter.sufe.edu.cn/info/356257)
- Gehricke & Zhang (cited in the same digest) attribute VXX's negative returns to roll yield: roll yield is "predominantly negative in normal times due to the contango term structure of VIX futures which is driven by the normally negative market price of variance risk." — [same digest](https://academicnewsletter.sufe.edu.cn/info/356257)
- Whaley (2013 draft, via press coverage): VIX ETPs fall in a "contango trap" because VIX futures prices exceed expected future VIX; the VIX Short Term Total Return Futures Index "fell by more than 93 percent since inception"; 2x leveraged TVIX holding-period return -99.96 percent; product returns correlated about -0.78 with benchmarks. Secondary summary, not the paper. — [Vanderbilt news](https://news.vanderbilt.edu/2013/10/18/volatility-etps/), [CXO](https://www.cxoadvisory.com/volatility-effects/buying-and-holding-exchange-traded-products-based-on-vix-futures)
- Alexander & Korovilas (2012 version, via CXO summary): since April 2009 VXX returned about -92% and VXZ about -46% (steeper short-dated slope hurts VXX more); constant-maturity VXX construct annual Sharpe -0.77; a third-generation portfolio switching between XVIX and XVZ on contango vs backwardation reported full-sample Sharpe 1.32. Digest says full text not seen. — [CXO enhanced VIX futures ETNs](https://www.cxoadvisory.com/volatility-effects/enhanced-vix-futures-etns), [CXO diversification](https://www.cxoadvisory.com/volatility-effects/diversification-with-vix-futures-and-related-etns)
- Simon & Campasano (EFMA 2013 draft; digest): basis has "little power to predict moves in spot VIX over 2006-2011, but it did predict subsequent VIX futures returns." Strategy: short VIX futures in contango / long in backwardation, hedged with E-mini S&P futures. Baseline: nearest contract with at least 10 trading days to maturity; entry when daily roll (futures minus spot divided by trading days to maturity) exceeds 0.10 points; 5-day hold. Costs assumed: $3 round trip per VIX futures contract plus full bid-ask spread, plus $12.50 for E-mini. Authors report results survive costs and out-of-sample hedge ratios. A practitioner summary quotes a 53% annual compound return, 2006-2011 (CXO). Quantpedia notes about half of the trade (the long side) is a crisis hedge and the short-vol half is not. Authors read the basis as a harvestable risk premium rather than a forecast of spot-VIX mean reversion. — [EFMA draft](https://www.efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2013-Reading/papers/EFMA2013_0164_fullpaper.pdf), [Quantpedia](https://quantpedia.com/strategies/exploiting-term-structure-of-vix-futures), [CXO](https://www.cxoadvisory.com/volatility-effects/timing-and-hedging-the-roll-return-for-vix-futures/)
- Static short-vol via ETPs: a Journal of Investment Strategies paper (data 2006-2017; title/authors not captured by digest) reports static short-vol "profitable in the long-term, but exhibit small Sharpe ratios (< 0.5), on account of the high volatility of VIX." — [Risk.net JIS](https://www.risk.net/journal-of-investment-strategies/5460971/statistics-of-vix-futures-and-their-applications-to-trading-volatility-exchange-traded-products)
- Cheng, "The Expected Return of Fear" (via CXO): selling nearest VIX futures when futures/VIX level > 1 gave gross average monthly excess return 4.3%, monthly vol 11.9%, gross monthly Sharpe 0.36; reported gross, and the author cautions frictions at roughly monthly turnover would reduce it. — [CXO](https://www.cxoadvisory.com/volatility-effects/timing-vix-futures-with-the-futures-spot-ratio/)
- CXO's study of VXX/SVXY 2009-2019: VXX futures roll return has modest predictive power for SVXY over 1-21 days (highest roll returns associated with weaker SVXY); VIX level, VRP and VVIX showed minimal predictive value; in-sample; SVXY leverage was cut from -1x to -0.5x in early 2018, which can break relationships. — [CXO identifying VXX/XIV tendencies](https://www.cxoadvisory.com/volatility-effects/identifying-vxxxiv-tendencies)
- Contradiction on "backwardation filter works": a QuantConnect backtest of "sell nearest future in contango, buy in backwardation" showed Sharpe -0.153 and 94.8% drawdown, whereas another trade-signal study reports Sharpe 2.24 and 2.6 (details, costs and period not given). Both are unverified single implementations. — [QuantConnect/Quantpedia backtest](https://quantconnect.com/terminal/quantpediaBacktestResult/embedded_backtest_8c8d6b135753cee8c2f4f7f540553b2a.html), [search digest page: luxalgo](https://www.luxalgo.com/library/concept/vix-term-structure/)

### Inferences
- The premium is real and large on average but arrives with crash-type tails; headline Sharpes of 1+ come from timing overlays tested on 2006-2013-ish samples, often gross of costs. Treat as upper bounds.
- The Alexander & Korovilas 1.32 and Simon-Campasano 53% figures are promotional-style in-sample numbers on a sample (2006-2011/2009-2012) that predates the 2018 and 2020 shocks.

### Gaps
- No full text of Eraker & Wu, Simon & Campasano, Alexander & Korovilas, Whaley was read; t-statistics, subsample splits and exact cost tables not obtained.
- Publication year/venue of Simon & Campasano (J. Derivatives 2014) and Whaley (JPM) not confirmed by my sources.
- Bollen/Whaley-type and Cboe white-paper evidence on put-write (PUT) index drawdowns: not retrieved.

---

## Q2. Conditioning short premium on term-structure slope; inverted curve as stop-trading signal; Volmageddon

### Takeaway
Direction of the evidence is consistent: a low/flat/inverted VIX term structure predicts low returns to being short variance, and high slope (steep contango) predicts higher returns. The best-documented source (Johnson) is a 1996-2013 in-sample academic study; the newest (Zarattini-Aziz-Mele, 2025) reports a VIX/VIX3M-based dual signal with Sharpe about 1 net of costs, but I only saw an abstract-level digest. No rigorous Volmageddon study of the inverted-curve stop rule was found.

### Cited Findings
- Johnson, "Risk Premia and the VIX Term Structure": VIX term structure built from six VIX values (1, 2, 3, 6, 9, 12 months) using S&P 500 options, 1996-2013. Slope did not forecast changes in VIX level, but forecast excess returns of S&P 500 variance swaps, VIX futures and index straddles at all maturities: "A relatively low (high) slope predicts relatively high (low) returns." Next-day return differences between lowest and highest slope quintiles range 0.29% to 1.81% across 18 asset/maturity combinations (CXO summary; sign convention is for the long position of each variance asset, so a low slope favors long-variance returns, i.e. it is a caution for short-vol sellers). Search digest also lists slope and implied-minus-expected variance as the strongest predictors of VRP tested. — [CXO summary](https://www.cxoadvisory.com/volatility-effects/vix-term-structure-slope-and-variance-asset-future-returns/)
- Note on direction: Johnson's "low slope predicts high returns" refers to returns of the variance assets (the long-variance side); for a seller, low slope = lower expected seller return. The digest did not spell out the short side; this is my reading and is flagged as inference below.
- Zarattini, Aziz, Mele, "The Volatility Edge: A Dual Approach for VIX ETNs Trading" (SFI WP 25-91, Oct 2025): four rule sets from constant short-vol to dynamically sized rules using an expected-VRP signal (from recent SPY realized volatility) and the VIX vs VIX3M term-structure slope. Reported 2008-2025, "after realistic costs", 16.3% per year compound, Sharpe about 1, equity correlation about 15%, and a 20% Sharpe uplift when a modest slice is blended into SPY. One summary has the rule using the 3:45pm VIX term structure, allocating VIXSHORT in contango and VIXLONG in backwardation. Sample start varies by summary (2005 vs 2008). Abstract/digest only; promotional tone ("edge") and a working paper, not peer reviewed. — [SFI](https://www.sfi.ch/de/publications/n-25-91-the-volatility-edge-a-dual-approach-for-vix-etns-trading), [IDEAS](https://ideas.repec.org/p/chf/rpseri/rp2591.html)
- QuantConnect reimplementation of the same logic with VIXY and SPY: Sharpe 0.729 (different window); community backtest, not independent validation. — [QuantConnect](https://www.quantconnect.com/research/21143/harvesting-the-volatility-risk-premium-with-a-dual-vix-signal/)
- VIX/VIX3M ratio definition and frequency: ratio of VIX close to VIX3M close; below 1 = contango, above 1 = backwardation; one tracker site says backwardation occurred on 7.7% of trading days since 2010 across 104 episodes (tracker site, not primary). — [luxalgo tracker](https://www.luxalgo.com/library/concept/vix-term-structure/)
- Alexander & Korovilas switching portfolio (contango -> short, backwardation -> long) Sharpe 1.32 (see Q1); CXO notes XVIX construct annual Sharpe 1.21 "performing best when VIX futures are in contango". — [CXO](https://www.cxoadvisory.com/volatility-effects/enhanced-vix-futures-etns), [CXO Johnson page digest](https://www.cxoadvisory.com/volatility-effects/vix-term-structure-slope-and-variance-asset-future-returns/)
- Conditional slope allocation (UMass dissertation, author not captured): time-varying allocation conditioned on the implied-vol term-structure slope; a three-asset portfolio of a VIX futures position, S&P 500 and cash substantially beats the index; a long-vol carry portfolio stays profitable after transaction costs; slope negatively predicts index option returns. Dissertation, unrefereed. — [UMass](https://scholarworks.umass.edu/entities/publication/36521585-82a0-4825-8e5e-6b0945a14abf)
- Practitioner heuristic (flag: NOT validated research): Concretum Group regime grid, full size when premium positive and curve normal, half size when premium compressed but curve calm, cash or long vol when curve inverted. — [Concretum](https://concretumgroup.com/automating-a-vix-volatility-strategy-with-python-and-interactive-brokers/)
- Volmageddon facts (news explainers, not research): VIX closed 17.31 on 2 Feb 2018 and 37.32 on 5 Feb 2018; Credit Suisse's XIV hit an "acceleration event" when intraday indicative value fell to 20% or less of the prior day's close. No academic analysis of the term-structure signal around the event was found. — [EBC explainer](https://www.ebc.com/forex/volmageddon-explained-when-volatility-turns-violent), [Interactive Brokers](https://www.interactivebrokers.com/campus/traders-insight/securities/macro/today-is-volmaggedons-sixth-anniversary/)

### Inferences
- Both Johnson and the Alexander/Zarattini rules imply "sell only when VIX < VIX3M (contango); step aside or cut when ratio > 1". Direction agrees; magnitude after costs is only supported by a 2025 working paper and one blog backtest, versus a contradictory unfiltered QuantConnect result. Evidence strength: moderate-low.
- An inverted curve is a contemporaneous stress state (backwardation about 7.7% of days per a tracker site); as a stop-trading rule it avoids the tail but also forfeits post-spike premium (spike days are when implied vol is richest). Not tested in the sources I saw.
- The Volmageddon episode shows the one-day gap risk that a daily-close slope rule cannot prevent: VIX went from 17.31 to 37.32 over two sessions from a calm contango state.

### Gaps
- No primary read of Johnson, Zarattini et al., or any Volmageddon academic study; drawdown-by-regime tables not obtained.
- No independent out-of-sample replication of the VIX/VIX3M rule found beyond a QuantConnect post.

---

## Q3. Volatility-regime signals: VVIX, regime-switching, drawdown clustering, size-reduction by VIX level/percentile

### Takeaway
Rigorous evidence is thin. VVIX shows a relation to returns in one 2006-2013 study but a later ETN test found "minimal predictive value"; a two-state HMM paper supports regime-based on/off timing; VIX-level scaling rules are mostly practitioner or single-working-paper evidence.

### Cited Findings
- Huang & Shaliastovich (2014), via CXO: higher VVIX predicts more negative returns for hedged S&P 500 and VIX futures options, with VIX futures options averaging -0.57% to -1.41% monthly (Feb 2006-Jun 2013, daily-hedged portfolios); monthly VIX-VVIX correlation only 0.30. Hedged option returns are the long-option side; negative means selling them earned that. — [CXO](https://www.cxoadvisory.com/volatility-effects/expected-volatility-of-stock-market-volatility-as-a-predictor/)
- Contradiction: the CXO 2009-2019 VXX/SVXY test found VIX level, VRP and VVIX gave minimal predictive value; roll return mattered more. In-sample. — [CXO](https://www.cxoadvisory.com/volatility-effects/identifying-vxxxiv-tendencies)
- A CXO-summarised VVIX term-structure study: gross annual Sharpe 1.50 for 1-month straddles vs 1.20 for short-only; results gross, not net (author not named in the digest). — [CXO](https://www.cxoadvisory.com/volatility-effects/vix-term-structure-slope-and-variance-asset-future-returns/)
- Dapena, Serur, Siri (CEMA WP 659, 2018): two-state Hidden Markov Model on US stock volatility; the volatility premium shows temporal breaks; strategy sells volatility in the favorable regime and holds Treasury bills otherwise; authors note selling vol is profitable "as long as proper risk management is under place". Abstract only; performance figures not obtained. — [CEMA](https://ucema.edu.ar/documento-trabajo/measuring-and-trading-volatility-us-stock-market-regime-switching-approach)
- Practitioner (flag): SpotGamma treats high VVIX as a sizing input (wide VIX outcome distribution); commentary, not a tested result. — [SpotGamma](https://spotgamma.com/vvix-explained-what-the-volatility-index-tells-traders/)
- Practitioner (flag): Harbourfront Quant Substack on VIX-based position sizing; content not retrieved. — [Harbourfront](https://harbourfrontquant.substack.com/p/using-the-vix-for-position-sizing)
- NY Fed Liberty Street (summarised): selling volatility by receiving fixed in 1-month S&P variance swaps earned a large and significant average return, but average returns from selling implied volatility were not as significant as those for selling realized volatility. — [NY Fed](https://libertystreeteconomics.newyorkfed.org/2021/02/equity-volatility-term-premia.html)

### Inferences
- Drawdown clustering is implicit in all sources (calm-state carry, crash-state gap) but I found no study quantifying clustering by VIX percentile for short-premium P&L.
- VIX-level scaling evidence rests on Wysocki (below) plus heuristics.

### Gaps
- No rigorous out-of-sample test of VIX-percentile size-reduction rules located.
- No full-text on HMM/regime papers; performance figures missing.

---

## Q4. Wysocki (2025), "Sizing the Risk: Kelly, VIX, and Hybrid Approaches in Put-Writing on Index Options" (arXiv 2508.16598)

### Takeaway
Full text was NOT reachable (arxiv.org, ideas.repec.org, alphaxiv, ResearchGate PDF all blocked or failed). What is known comes from the abstract and search snippets only, with at least one garbled numeric snippet. It is a single-author, 0-5 DTE SPXW study with a very recent, short-sample focus; it should be treated as weak evidence for the Nifty router.

### Cited Findings
- Metadata: Maciej Wysocki, University of Warsaw, submitted 9 Aug 2025, q-fin.PM. Search results also list a Knowledge-Based Systems vol 348 entry (ACM DL / ScienceDirect) but a later digest could not confirm the venue, so treat as unconfirmed. — [arXiv](https://arxiv.org/abs/2508.16598), [ACM DL listing](https://dl.acm.org/doi/10.1016/j.knosys.2026.116331)
- Abstract-level design: compares Kelly-criterion sizing, VIX-based volatility-regime scaling and a novel hybrid of both for systematic put-writing on S&P 500 index options (SPXW) with 0 to 5 days to expiry. — [arXiv](https://arxiv.org/abs/2508.16598)
- Grid per a snippet: DTE 0, 1, 3, 5; OTM 0%, 2%, 5%, 10%; also varies volatility estimators and "memory horizons". Probabilistic Sharpe Ratio (Bailey & Lopez de Prado) used because returns are negatively skewed/fat-tailed. [UNVERIFIED, from a search digest of arXiv text] — [arXiv PDF](https://arxiv.org/pdf/2508.16598)
- Abstract claims: ultra-short-dated, far-OTM options give superior risk-adjusted returns; the hybrid "consistently balances return generation with robust drawdown control, particularly under low-volatility conditions such as those seen in 2024." — [arXiv](https://arxiv.org/abs/2508.16598)
- Numbers seen in snippets [UNVERIFIED, garbled]: Kelly strategies kept max drawdowns low in 0-1 DTE setups with returns about 2.5% to 17.2%; best case 1 DTE at 5% OTM with roughly 14% to 17% returns and about 8.5% volatility; a ResearchGate snippet cited far OTM (5-10%), 0-1 DTE as best and one configuration (VIX9D, 21-day memory) at 52.77% return, 21.59% volatility, 9.91% max drawdown. The two sets of numbers are not reconcilable from snippets (different configs/windows unknown). — [arXiv](https://arxiv.org/pdf/2508.16598), [ResearchGate](https://www.researchgate.net/publication/394942155_Sizing_the_Risk_Kelly_VIX_and_Hybrid_Approaches_in_Put-Writing_on_Index_Options)
- A blog summary says the hybrid uses Monte Carlo forecasting with real-time volatility signals; unverified. — digest of search results for [arXiv](https://arxiv.org/abs/2508.16598)
- Pith.science flagged that its read rested on the abstract only and performance claims were not independently verified. — [Pith](https://pith.science/paper/2508.16598)

### Inferences
- Even taken at face value, the evidence is for hybrid sizing's drawdown control in 2024, a one-year low-vol regime, with 0-5 DTE contracts (not monthly/weekly Nifty structures). The sample window, transaction-cost treatment (spreads, fees, margin) and number of configurations tested (multiple-testing risk across 4x4 DTE/OTM grid plus estimators and memory horizons) are unknown to me.
- Reported return figures like 52.77% with 9.91% drawdown on a single best grid cell look like selection from a grid; cannot be treated as a robust estimate.

### Gaps (substantial)
- Data source, sample dates, frequency, margin/capital assumptions, costs/slippage, exact Kelly estimator, exact VIX scaling thresholds, hybrid formula, full result tables, robustness, stated limitations: all NOT obtained. A reader with network access should fetch https://arxiv.org/pdf/2508.16598 and fill these.

---

## Q5. Replication, decay, sample dependence, conflicts

### Takeaway
Samples cluster in 2006-2013; products and rules changed after 2018 (SVXY leverage cut, XIV termination); the newest pro-timing evidence (2025) is a working paper with promotional framing and only a blog-level replication (Sharpe 0.729 vs paper's about 1).

### Cited Findings
- Sample dependence: Eraker & Wu 2006-2013; Simon & Campasano 2006-2011; Johnson 1996-2013; Huang & Shaliastovich Feb 2006-Jun 2013; JIS static short-vol 2006-2017 (Sharpe < 0.5). Sources as cited above.
- Conflicts: (a) VVIX predictive (Huang & Shaliastovich) vs minimal (CXO 2009-2019 SVXY test); (b) term-structure switching Sharpe 1.32 / 2.24 / 2.6 vs QuantConnect -0.153 with 94.8% drawdown; (c) Zarattini et al. Sharpe about 1 vs QuantConnect replication 0.729 (different window and instruments). Sources above.
- Caveat on CXO-style summaries: CXO flags in-sample testing and gross-of-cost returns (e.g. Cheng's 4.3% monthly). — [CXO](https://www.cxoadvisory.com/volatility-effects/timing-vix-futures-with-the-futures-spot-ratio/)
- The same NY Fed note observes that selling implied vol has been less significant than selling realized vol. — [NY Fed](https://libertystreeteconomics.newyorkfed.org/2021/02/equity-volatility-term-premia.html)

### Inferences
- Decay cannot be quantified from what I read; no source reported a before/after-publication split.
- Promotional-bias flags: Zarattini et al. (title "The Volatility Edge"), Quantpedia/CXO headline numbers, Concretum thresholds, QuantConnect forum posts.

### Gaps
- No post-publication decay study located. No Cboe white paper retrieved.

---

## Q6. Implications for the regime router and sizing in a Nifty backtester

### Takeaway
Evidence supports a small set of simple, testable overlays (term-structure gate, VIX-percentile size taper, vol-of-vol gate), but all come from US VIX-futures/SPX samples, mostly 2006-2017, and none are cost-validated on Nifty. Treat each as a hypothesis to test with the existing chain engine (real settle prices, slippage multipliers 1.0/1.5/2.0x) and permutation/walk-forward tools, and pre-register the verdict.

### Context from this repo (CLAUDE.md)
- India has India VIX futures but no listed VIX options (per task brief; not independently verified here). Near/far Nifty option IV can be taken from the NSE F&O bhavcopy archive via `data/nse_fo_archive.py` / `backtester/chain_engine.py`; that archive has no bid/ask and only EOD settle, so IV must be inverted from settle prices. The existing router already uses VIX zones (BWB 22-30), circuit breakers (50d drawdown -18%, crash score >= 0.80), `vix_simultaneous_cap` 25 and a DD kill-switch; chain-engine verdict so far is expectancy -177/-238/-348 Rs/lot at 1.0x/1.5x/2.0x slippage (NOT SUPPORTED), so any overlay must first be tested to see whether it can create positive expectancy, not just reduce drawdown.

### Cited Findings (design inputs, with provenance)
- Term-structure sign as gate: contango = collect, backwardation = stand aside/hedge (Johnson; Simon & Campasano; Alexander & Korovilas; Zarattini et al.) — see Q1/Q2 sources.
- Daily roll threshold from Simon & Campasano: (futures - spot) / trading days to maturity > 0.10 index points, >= 10 trading days to maturity, 5-day holding (EFMA draft). — [EFMA](https://www.efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2013-Reading/papers/EFMA2013_0164_fullpaper.pdf)
- VIX/VIX3M ratio 1.00 as threshold (tracker definition). — [luxalgo](https://www.luxalgo.com/library/concept/vix-term-structure/)
- Dual signal: expected VRP from recent realized vol minus implied level, plus slope (Zarattini et al.). — [SFI](https://www.sfi.ch/de/publications/n-25-91-the-volatility-edge-a-dual-approach-for-vix-etns-trading)
- Regime on/off via 2-state HMM (Dapena et al.). — [CEMA](https://ucema.edu.ar/documento-trabajo/measuring-and-trading-volatility-us-stock-market-regime-switching-approach)

### Inferences: concrete testable rules (all hypotheses, none validated for Nifty)
1. **Chain-IV term-structure gate.** Slope = IV(next-month ATM, from chain settle) / IV(current-week or front ATM) or (far - near)/near; sell only when far IV >= near IV (contango), skip or halve when near > far (inverted). Compare against the existing VIX-zone router, and as a proxy for VIX/VIX3M use India VIX vs a 60-90 day IV from the monthly chain. Evidence strength: moderate-low (US, 2006-2013 in-sample, plus a 2025 working paper). Failure modes: ATM IV from EOD settle is noisy; weekly-expiry IV is distorted by expiry-day effects and the Thursday-to-Tuesday cutover (2025-09-01); inverted days are rare (US about 7.7%), so the filter may change little and cut off the richest premium days; gap risk (Volmageddon type) is not prevented by a daily-close signal.
2. **India VIX futures basis (futures minus spot India VIX) and roll.** Mirror Simon & Campasano's daily roll > threshold; requires India VIX futures history, which I did not source; liquidity in India VIX futures is unverified here. Evidence: moderate for the US signal; not applicable until Indian data checked. Failure modes: thin liquidity, sparse history.
3. **VRP gate (implied minus forecast realized vol).** Sell only when India VIX (or chain ATM IV) exceeds trailing realized vol by a margin; part of Zarattini et al.'s dual signal. Evidence: low-moderate; CXO's SVXY test found VRP had minimal predictive value, a direct conflict. Failure mode: realized-vol estimator choice multiplies the number of configurations (overfitting).
4. **Size taper by VIX level/percentile** (e.g. reduce lots when VIX is in the top rolling-percentile bucket or above a level such as the existing 25 simultaneous cap). Evidence: weak. Wysocki's VIX scaling is abstract-level only and unverified; the practitioner sources are heuristics. Failure mode: shorting vol cheaply after spikes (forfeits premium) vs raising size into rising vol; test monotonic vs inverse taper both ways and report both.
5. **Vol-of-vol gate** (no India VVIX exists as far as I know; construct from rolling stdev of daily India VIX changes or of chain IV). Evidence: conflicting (Huang & Shaliastovich 2006-2013 supportive; CXO SVXY 2009-2019 minimal). Failure mode: proxy construction unvalidated.
6. **Two-state HMM on VIX or realized vol as on/off or size multiplier** (Dapena et al.). Evidence: low (abstract only, US). Failure modes: look-ahead if fit on full sample (must fit expanding-window), regime lag, label instability.
7. **Kelly / hybrid sizing** (Wysocki). Evidence: weak (see Q4). Failure modes: Kelly on negatively skewed P&L overbets; estimate error; test fractional Kelly with caps and compare with the existing `monthly_max_lots_cap` 30 and the DD kill-switch.
8. **Evaluation protocol (from caveats above):** apply every rule at 1.0/1.5/2.0x slippage on the chain engine; use walk-forward and permutation tests already in `--mode validate`; count number of variants tried; report subperiod stability (pre/post 2020, Tuesday-expiry era), and compare against a trivial baseline (always-on). A rule that only improves max drawdown but leaves expectancy negative should not be treated as an edge.

### Gaps
- No Nifty/India-specific term-structure studies were searched for in this note (India VIX futures basis, NSE weekly-vs-monthly IV slope); the scope of this note was US/global literature, so this remains an open lead.
- Full-text verification of every cited paper, including Wysocki, is outstanding because of the network restrictions described at the top.
