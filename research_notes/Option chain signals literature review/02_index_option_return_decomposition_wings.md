# Index option return decomposition (jump / volatility / skew) and the economics of OTM wings and hedges

**Access limitations (read first).** I read NO paper in full text. WebFetch failed with `getaddrinfo ENOTFOUND` for every host tried: ideas.repec.org, kops.uni-konstanz.de, deepblue.lib.umich.edu, researchonline.lse.ac.uk, m.nber.org, www.nber.org, papers.ssrn.com, www.cxoadvisory.com, academic.oup.com, scholarsarchive.byu.edu, econpapers.repec.org, arxiv.org, business.columbia.edu, drupalgsb-test.paas.cc.columbia.edu. A curl attempt through the proxy returned 403 `connect_rejected` for m.nber.org, www.alphaxiv.org and api.semanticscholar.org (host not allowed for the session). An attempt to read the proxy status page was denied by the permission classifier and I did not work around it. Everything below therefore comes from WebSearch result summaries: abstracts and secondary descriptions produced by the search tool, not verbatim text from the papers. Where a number appears it is the number the search summary reported, and it is tagged with its provenance (working paper vs published version, as the summary states). No t-statistics, no per-moneyness return tables, and no cost-treatment details could be retrieved for any paper; those are Gaps. Nothing has been filled in from memory.

Paper metadata, all confirmed by search summaries:

| Paper | Venue | Read | Text URLs surfaced by search |
|---|---|---|---|
| Broadie, Chernov, Johannes, "Understanding Index Option Returns", 2009 | Review of Financial Studies 22(11), 4493-4529 | abstract/secondary only | https://papers.ssrn.com/abstract=965739 ; https://business.columbia.edu/sites/default/files-efs/pubfiles/3964/broadie_chernov_johannes.pdf ; http://www.columbia.edu/~mnb2/broadie/Assets/EOR_20080618.pdf ; https://users.nber.org/~confer/2007/si2007/AP/chernov.pdf (none fetchable) |
| Bondarenko, "Why Are Put Options So Expensive?", 2014 | Quarterly Journal of Finance 4(3), 1450015 | abstract/secondary only | https://ideas.repec.org/a/wsi/qjfxxx/v04y2014i03ns2010139214500153.html ; https://www3.gmu.edu/schools/vse/seor/studentprojects/graduate/2009Fall/ISG/Investment_Optimization/Resources_files/Bondarenko-Puts.pdf (working paper copy; not fetchable) |
| Constantinides, Jackwerth, Savov, "The Puzzle of Index Option Returns", 2013 | Review of Asset Pricing Studies 3(2), 229-257, doi:10.1093/rapstu/rat004 | abstract/secondary only | https://www.ssrn.com/abstract=1491469 ; https://pages.stern.nyu.edu/~asavov/alexisavov/Alexi_Savov_files/ThePuzzleOfIndexOptionReturns.pdf |
| Constantinides, Jackwerth, Perrakis, "Mispricing of S&P 500 Index Options", 2009 | Review of Financial Studies 22, 1247-1277 (NBER WP 14544, Dec 2008) | abstract/secondary only | https://www.nber.org/system/files/working_papers/w14544/w14544.pdf |
| Coval, Shumway, "Expected Option Returns", 2001 | Journal of Finance 56(3), 983-1009, doi:10.1111/0022-1082.00352 | abstract/secondary only | https://www.ssrn.com/abstract=189840 ; https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00352 |

---

## Broadie, Chernov & Johannes (2009): are index put returns evidence of mispricing, and what is the volatility vs jump premium?

### Takeaway
BCJ argue that the famously large returns from writing OTM index puts are statistically not inconsistent with Black-Scholes or simple stochastic-volatility models without risk premia, because option returns have extreme sampling error. Straddle (market-neutral) returns are harder to explain and are attributed to jump risk premia (plus Peso problems and estimation risk in the working paper). Only abstract-level material was accessible.

### Cited Findings
- Published as Review of Financial Studies 22(11):4493-4529 (2009). Authors: Mark Broadie, Mikhail Chernov, Michael Johannes. The search summary says the earlier 2007 SSRN version lists a different author order. — [SSRN abstract 965739](https://papers.ssrn.com/abstract=965739)
- Core argument as summarised: the authors challenge the claim that index puts are mispriced, because earlier benchmarks handle the extreme statistical nature of option returns poorly. They propose judging significance by comparing historical statistics with those produced by option pricing models. — [SSRN abstract 965739](https://papers.ssrn.com/abstract=965739)
- The large returns from writing OTM puts "are not even inconsistent with the Black-Scholes model" (2007 working-paper abstract wording as reported by the search summary). Simple stochastic-volatility models with no risk premia produce put returns across all strikes that fit the observed data. — [SSRN abstract 965739](https://papers.ssrn.com/abstract=965739); [Columbia working draft](https://business.columbia.edu/sites/default/files-efs/pubfiles/3964/broadie_chernov_johannes.pdf)
- The Columbia working draft says put returns are not inconsistent (i.e., statistically insignificant deviations) relative to Black-Scholes or Heston. — [Columbia working draft](https://business.columbia.edu/sites/default/files-efs/pubfiles/3964/broadie_chernov_johannes.pdf)
- ATM straddle returns are "more challenging" and, per the 2007 working-paper abstract, are "not inconsistent with" jump risk premia, Peso problems and estimation risk. The published RFS abstract is narrower and does not mention straddles or Peso problems. — [SSRN abstract 965739](https://papers.ssrn.com/abstract=965739)
- A secondary description says sampling noise can be reduced by studying straddles or delta-hedged returns; straddle returns, unlike single-option returns, are inconsistent with Black-Scholes and SV models that have no risk premia beyond the equity premium, and are explained by jump risk premia and estimation risk, so jump risk premia "play a very important role" in the return magnitudes. This is a search-tool synthesis of working-paper material, not a verbatim quote. — [Columbia working draft](https://business.columbia.edu/sites/default/files-efs/pubfiles/3964/broadie_chernov_johannes.pdf); [Columbia listing](https://business.columbia.edu/faculty/research/understanding-index-option-returns-0)
- Companion paper (different data, so do not conflate): "Model Specification and Risk Premia: Evidence from Futures Options" (same authors, Journal of Finance 2007) is summarised as finding no statistically significant diffusive volatility risk premium but modest, statistically and economically significant jump risk premia. This claim is from a search-tool summary of a different paper that I did not open. — [BCJ JF 2007 PDF](http://www.columbia.edu/~mnb2/broadie/Assets/BCJ_jf_2007.pdf)
- Sharpe ratios are used as a diagnostic and give results similar to average option returns (search summary; no Sharpe table retrieved). — [Columbia working draft](https://business.columbia.edu/sites/default/files-efs/pubfiles/3964/broadie_chernov_johannes.pdf)

### Inferences
- If the paper is right, "put-writing earns a large premium" is weak statistical evidence of a harvestable edge for a short sample: the premium is dominated by rare jump outcomes, and a few years of backtest cannot distinguish "fair compensation for jumps" from "mispricing". Apply this directly to a Nifty backtest of a few years.
- The jump-premium reading implies the OTM-put share of returns is mostly compensation for crash risk, whereas the straddle/ATM residual is where the volatility/jump premium is statistically detectable. This is an inference from the abstracts, not a tested result.

### Gaps
- Data description (S&P 500 options, sample period, frequency, maturities, moneyness grid): not retrieved.
- Per-moneyness mean returns, Sharpe ratios, p-values and the exact model parameter estimates for the jump and volatility premia: not retrieved.
- Transaction-cost treatment and robustness checks: not retrieved.
- Confirmation of which claims are in the published RFS text versus only the 2007 working-paper abstract.
- Index vs single stock: the search summaries describe S&P 500 index options only; US only. No non-US evidence in these sources.

---

## Bondarenko (2014): are puts mispriced or compensated for risk? Put-writing returns, Sharpe, drawdown

### Takeaway
Bondarenko's QJF paper concludes that no model in the class he studies explains the "overpriced puts puzzle", using a model-free approach. His later Cboe white paper shows PUT-index returns near the S&P 500 with lower volatility and drawdown. Only abstracts, working-paper copies and secondary summaries were accessible.

### Cited Findings
- Published in Quarterly Journal of Finance 4(3), 1450015 (2014); full text is behind a paywall, so what follows is abstract plus secondary summaries. — [IDEAS](https://ideas.repec.org/a/wsi/qjfxxx/v04y2014i03ns2010139214500153.html)
- Main conclusion as summarised: the "overpriced puts puzzle" (historical S&P 500 put prices too high to fit canonical asset-pricing models) cannot be explained by any model in the class studied. The approach is model-free (no parametric assumptions about preferences) and is robust to selection biases such as the Peso problem; it builds on Bondarenko's 2003 methodology. — [IDEAS](https://ideas.repec.org/a/wsi/qjfxxx/v04y2014i03ns2010139214500153.html)
- Working-paper figures (not confirmed in the published version, per the search summary): average excess returns of about -39% per month for ATM puts and -95% per month for deep OTM puts (these are returns to the put BUYER, so the seller earns the mirror image before margin and tail losses). — [Bondarenko working paper](https://www3.gmu.edu/schools/vse/seor/studentprojects/graduate/2009Fall/ISG/Investment_Optimization/Resources_files/Bondarenko-Puts.pdf)
- An older (2004) working-paper summary reported Jensen's alpha for selling ATM index puts of a highly significant 23% per month; the search summary warns it may differ from the published version. — [CXO Advisory summary](https://www.cxoadvisory.com/equity-options/is-40-per-month-shorting-index-puts-a-fair-return)
- Working paper: Sharpe ratio for selling puts exceeds the market's, with the gap largest for ATM and OTM puts, with a caution that Sharpe ratios can mislead when returns are strongly skewed. — [Bondarenko working paper](https://www3.gmu.edu/schools/vse/seor/studentprojects/graduate/2009Fall/ISG/Investment_Optimization/Resources_files/Bondarenko-Puts.pdf)
- Follow-up: Bondarenko (2019), "Historical Performance of Put-Writing Strategies", Cboe PUT index (cash-secured ATM monthly S&P 500 put-writing), June 1986 to December 2018: annual compound return 9.54% (PUT) vs 9.80% (S&P 500); standard deviation 9.95% vs 14.93%; Sharpe 0.65 (PUT) and 0.49 (S&P 500) per the SSRN abstract; maximum drawdowns 24.2% (WPUT, weekly index, from 2006 only), 32.7% (PUT), 50.9% (S&P 500). The same search summary notes a Cboe-hosted PDF fragment showing different Sharpe figures (0.50 and 0.51), so the Sharpe numbers need checking against the paper's own table; the drawdown windows are also ambiguous. — [SSRN 3393940](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3393940); [Cboe PDF](https://cdn.cboe.com/resources/spx/bondarenko-oleg-putwrite-putw-2019.pdf)
- The 2019 paper attributes the PUT index's risk-adjusted advantage to a high volatility risk premium, since implied volatility has considerably exceeded realised volatility. A separate search summary lists a Sharpe of 0.33 for PPUT (the protective-put index). — [Cboe insights post](https://www.cboe.com/insights/posts/white-paper-shows-volatility-risk-premium-facilitated-higher-risk-adjusted-returns-for-put-index)
- Corroboration: Chambers, Foy, Liebner and Lu (RFS 2014) are reported to reject the hypothesis that put returns are consistent with option pricing models. — [IDEAS](https://ideas.repec.org/a/wsi/qjfxxx/v04y2014i03ns2010139214500153.html)
- CONFLICT with Broadie-Chernov-Johannes: BCJ say put-writing returns are statistically not inconsistent with Black-Scholes/SV without risk premia (sampling noise), while Bondarenko says no model in his class explains them and uses a model-free approach designed to be robust to Peso-type selection. The two papers are about the same facts and reach opposite statistical conclusions. — [BCJ](https://papers.ssrn.com/abstract=965739) vs [Bondarenko](https://ideas.repec.org/a/wsi/qjfxxx/v04y2014i03ns2010139214500153.html)
- Related: Bondarenko's "An Analysis of Index Option Writing with Monthly and Weekly Rollover" exists (SSRN 2750188), which matters for a weekly-expiry seller, but I only saw its title. — [SSRN 2750188](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2750188)

### Inferences
- The 9.54% vs 9.80% return with 32.7% vs 50.9% drawdown shows ATM put-writing is a leveraged-equity-like exposure with the same tail character, only diluted by lower volatility; it is not a free lunch. The risk-adjusted advantage is real in the sample but is concentrated in the large drawdowns of 1987, 2008 and 2020-type events, which this review could not break out.
- Because mean put returns are dominated by few crash episodes, the Sharpe ratio overstates quality for strategies with strongly negative skew (the paper's own caution).

### Gaps
- Published QJF figures (the -39% and -95% are working-paper numbers). Sample period, frequency and moneyness grid for the 2014 paper: not retrieved.
- Transaction-cost treatment (the Cboe PUT index is frictionless); robustness; t-stats: not retrieved.
- Which of the 0.65/0.49 vs 0.50/0.51 Sharpe pairs is correct for which index/window: unresolved.
- US index only in these sources; no India/Nifty evidence.

---

## Constantinides, Jackwerth & Savov (2013) and Constantinides, Jackwerth & Perrakis (2009): returns by moneyness and maturity, transaction costs, what is exploitable

### Takeaway
CJS (2013) find S&P 500 option returns vary systematically with the strike-to-price ratio and that only crash-type factors (market jumps, volatility jumps, liquidity) explain the cross-section, pointing towards risk compensation rather than free mispricing. CJP (2009) find stochastic-dominance violations after transaction costs, but only for one-month CALLS, and not mainly in the left tail. Abstract-level only.

### Cited Findings
- CJS: Review of Asset Pricing Studies 3(2):229-257 (2013). Leverage-adjusted returns on S&P 500 call and put portfolios decrease in the strike-to-price ratio, contrary to Black-Scholes-Merton. Sample period varies by version: 1986-2007 (early draft), 1986-2009 (published, per one summary), 1986-2010 (SSRN version). — [SSRN 1491469](https://www.ssrn.com/abstract=1491469); [Semantic Scholar entry](https://www.semanticscholar.org/paper/The-Puzzle-of-Index-Option-Returns-Constantinides-Jackwerth/d13b9a1949543260e4ea3b3059cb78edfc2e6852)
- CJS: portfolios are adjusted daily to a targeted maturity, moneyness and unit market beta; monthly portfolio returns have low skewness and are close to normal, so linear factor models can be used. — [Konstanz repository summary via search](https://kops.uni-konstanz.de/server/api/core/bitstreams/d9eb4523-5c7e-45ad-9f79-7365493dd758/content)
- CJS: of the many factor models tested, only factors capturing jumps in the market index and jumps in market volatility (and, to a lesser extent, volatility and liquidity) reasonably explain the cross-section; the crisis-factor hypothesis is not rejected even with factor premia constrained to equal those in the equity cross-section (per one summary, in the published version). The authors say these factors need different premia across calls and puts, maturities and moneyness, pointing to market segmentation. Earlier drafts: Fama-French factors left large alphas; the change in monthly OTM put volume and the change in the VIX helped somewhat. — [SSRN 1491469](https://www.ssrn.com/abstract=1491469); [OptionMetrics summary](https://optionmetrics.com/?p=1021)
- CJS online appendix includes robustness checks, including removal of screening filters when buying into an option portfolio. — [Konstanz working paper listing](https://kops.uni-konstanz.de/entities/publication/02d5061a-4d95-4381-8d7f-6104621d086d/full)
- CJP: Review of Financial Studies 22:1247-1277 (2009); NBER WP 14544. Reports widespread stochastic-dominance violations in one-month S&P 500 index CALL options over 1986-2006 (an earlier version covers 1986-2002): a trader can improve expected utility by a zero-net-cost trade net of transaction costs and bid-ask spread. Bounds derive from Constantinides-Perrakis (2002). — [NBER WP 14544](https://www.nber.org/system/files/working_papers/w14544/w14544.pdf); [SSRN 1359522](https://ssrn.com/abstract=1359522)
- CJP: pre-crash prices fit Black-Scholes-Merton reasonably well but are mispriced if the index return distribution is estimated from time-series data; substantial violations by post-crash OTM calls suggest the problem is not mainly in the left tail, or that the smile is too steep. — [NBER WP 14544](https://www.nber.org/system/files/working_papers/w14544/w14544.pdf)
- Follow-up: Constantinides, Czerwonko & Perrakis (NBER WP 23708, 2017; Financial Management 2020) report that an optimal index-plus-cash portfolio with proportional transaction costs becomes stochastically dominated when overlaid with a zero-net-cost option portfolio (bought at ask, written at bid) in most months over 1990-2013, and that this is explained neither by priced factors nor by a non-monotonic SDF. — [NBER WP 23708](https://www.nber.org/system/files/working_papers/w23708/w23708.pdf); [Wiley](https://onlinelibrary.wiley.com/doi/10.1111/fima.12288)
- Tension within this literature: CJS (risk factors explain the cross-section) vs Constantinides-Czerwonko-Perrakis (not explained by priced factors) vs BCJ (nothing to explain once sampling error is accounted for). — sources above

### Inferences
- CJP's violations are in calls, not puts. They do not directly say OTM puts are rich; do not cite CJP as support for selling puts.
- CJS's monotone return pattern across strikes (leverage-adjusted returns falling in the strike/price ratio) is consistent with the wings being where crash compensation is concentrated; the factor result says that compensation is risk, so selling the extreme wings is not an arbitrage.

### Gaps
- Actual leverage-adjusted return levels by moneyness bucket and maturity, t-statistics and alphas: not retrieved.
- Transaction cost treatment specifics for CJS (the summaries give none); CJP's bid-ask handling beyond "net of transaction costs and bid-ask spread".
- Whether the CJS published version (not working drafts) retains each claim above.

---

## Coval & Shumway (2001): zero-beta straddles and what they imply

### Takeaway
Under mild assumptions, expected call returns exceed the underlying's and rise with strike, and expected put returns are below the risk-free rate and rise with strike; zero-beta ATM straddles lost about 3% per week, suggesting a priced stochastic-volatility (or similar) factor. Abstract-level only.

### Cited Findings
- Journal of Finance 56(3):983-1009 (2001). Abstract: expected call returns exceed the underlying's and increase with strike; expected put returns are below the risk-free rate and increase with strike; S&P index option data match the patterns. — [SSRN 189840](https://www.ssrn.com/abstract=189840); [Wiley](https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00352)
- Zero-beta ATM straddles lost about three percent per week on average, suggesting another priced factor such as systematic stochastic volatility. One secondary source reports -3.15% per week on average for 1990-1995; the search tool could not confirm the sample period from other sources. — [Wiley abstract](https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00352); [BYU repository](https://scholarsarchive.byu.edu/facpub/9281/)
- Data: S&P 500 and S&P 100 index options; the authors also form zero-beta straddles with futures options on US T-bonds, Eurodollar, Nikkei 225 and Deutsche Mark (per search summary, one secondary source). — [Quantpedia summary](https://quantpedia.com/strategies/volatility-risk-premium-effect)
- Fama-MacBeth-style option return regression intercepts are reported as significantly below zero. — [Wiley abstract](https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00352)
- Replication: a 2021 Lisbon master's thesis reports similar results on S&P 500 options for 2004-2019 (a thesis, low quality); an Investment Analysts Journal paper studies expected option returns "during the post-GFC era" but I did not read its findings. — [Lisbon repository](https://repositorio.ulisboa.pt/entities/publication/75a4de0a-16a8-4562-904c-78b1ca3fa02c); [IAJ](https://www.tandfonline.com/doi/full/10.1080/10293523.2020.1759924)

### Inferences
- A -3% per week straddle loss is for a buyer; the mirror image for a straddle seller is a positive average gross of costs, but straddle writing is exactly the exposure BCJ attribute to jump premia, and Coval-Shumway's own interpretation is a priced volatility factor, so the "edge" is compensation for volatility-spike risk.
- The put prediction (expected return below risk-free and rising in strike) implies the buyer of a deeper OTM put has the lowest expected return per dollar, i.e. protective wings are the most expensive per unit of premium.

### Gaps
- Sample period (1986-1995 vs 1990-1995 conflict between sources), t-statistics, cost treatment, and the actual per-strike return table: not retrieved.

---

## Do OTM put (wing) premiums look too rich, and what does that mean for buying wings vs selling naked?

### Takeaway
Evidence retrieved says rolling long OTM puts has been a long-run drag; Chambers-Foy-Liebner-Lu say OTM puts may carry a premium over model fair value. I found no direct empirical comparison of put spreads vs naked puts; any statement about spread vs naked is inference.

### Cited Findings
- Cboe PPUT (buys one-month S&P 500 puts about 5% OTM): about 7.7% annualized vs 10.8% for the S&P 500 total return over July 1986 to May 2025 per Asness, Cao, Ilmanen and Villalon (2025) as relayed by a Summitward summary (secondary, not the paper). A Wilshire study for Cboe, 1986-2018, shows a shallower worst drawdown for PPUT (-38.9% vs -51.0%). — [Summitward](https://summitward.com/learn/tail-risk-hedging)
- AQR study of a rolling one-month 5% OTM put reportedly cut S&P 500 excess return from 5.1% to 1.8% a year over 1996-2016 (via an Endowus article; secondary). — [Endowus](https://endowus.com/insights/option-hedging-cost)
- Chambers, Foy, Liebner and Lu (RFS 2014; 1987-2012 index options): buying OTM puts for tail protection may carry a significant premium over model-implied fair value (via Summitward). — [Summitward](https://summitward.com/learn/tail-risk-hedging)
- Israelov's research (via Benzinga): holding less equity and more cash gave better downside protection than PPUT at similar expected return. Secondary; not verified. — [Benzinga](https://www.benzinga.com/etfs/broad-u-s-equity-etfs/25/03/44501856/do-puts-pay-off-evaluating-long-term-s-p-500-protection)
- A Journal of Investment Consulting study of monthly cash-secured S&P 500 puts at 2.5%, 5%, 10% OTM found annual exercise probabilities of about 84%, 56%, 27%. — [Investments & Wealth Institute](https://investmentsandwealth.org/advisor-publications/blog/journal-of-investment-consulting-mitigating-loss-trauma)
- A Copio blog backtest of 30% OTM puts on a 2% annual budget (2008-2025) reportedly limited maximum drawdown to 30.8% vs 51.9% (single backtest; low reliability). — [Copio](https://copiocapital.com/blog/protect-portfolio-from-crash-put-options)

### Inferences
- A short iron condor's long put wing is a purchase of exactly the contract these studies show to be costly in expectation; but a defined-risk wing also caps the left-tail payoff that, per BCJ/CJS, represents most of the compensated risk. Net effect on expected return is therefore ambiguous and must be measured, not assumed.
- Selling the near wing and buying a far wing (spread width) trades off premium collected vs hedge cost: wider wings should cost less in absolute terms but protect less of the tail. This is untested here.

### Gaps
- No peer-reviewed paper retrieved comparing put spreads, iron condors or BWBs with naked short puts in expected return or tail risk. This is the central gap for the backtester question.
- Chambers et al. were not read directly; AQR/Asness numbers are secondary.
- No evidence at all on NSE/Nifty options in any retrieved source.

---

## Replication, decay, sample dependence, conflicts

### Takeaway
Sample period differs across versions of every paper (CJS 1986-2007/2009/2010; CJP 1986-2002/2006; Coval-Shumway 1990-1995 vs unconfirmed 1986-1995), and the conclusions conflict on statistical significance (BCJ vs Bondarenko). No decay analysis was retrievable.

### Cited Findings
- Sample-period shifts across versions: CJS and CJP, see above. — [SSRN 1491469](https://www.ssrn.com/abstract=1491469); [NBER WP 14544](https://www.nber.org/system/files/working_papers/w14544/w14544.pdf)
- BCJ vs Bondarenko conflict on whether put returns are statistically distinguishable from a no-premium model. — see above
- Constantinides-Czerwonko-Perrakis find violations in most months over 1990-2013, which extends the CJP result but remains an index-option, US sample. — [NBER WP 23708](https://www.nber.org/system/files/working_papers/w23708/w23708.pdf)

### Inferences
- A "premium disappears after publication" test was not found in these sources; do not assert decay or no decay.

### Gaps
- Post-2010 and post-publication performance of the OTM-wing premium (other than the PPUT/PUT index figures above): not retrieved.
- Weekly-expiry era evidence beyond the title of Bondarenko's monthly/weekly rollover paper.

---

## Implications for a Nifty iron condor / credit spread / BWB backtester

All items are hypotheses to test, derived from abstract-level evidence on US index options; none has been verified on NSE data, and none of the literature found tests condors, spreads or BWBs directly.

1. **Treat tail-wing premium as mostly risk compensation, not a free edge (BCJ, CJS, Coval-Shumway).** Do not tune strikes to maximise backtested premium in the far-OTM put region; report results with and without the crash windows (e.g. 2008, 2020, 2022 per the repo's stress mode) so the contribution of rare events is visible. BCJ's point implies a short backtest cannot establish the put premium is mispricing.
2. **Test wing width as a parameter, not a constant.** Rule: for each short strike (e.g. 0.10-0.20 delta), sweep the long-wing distance (e.g. 100/200/300/500 Nifty points) and report expected P&L, worst day and max drawdown. Hypothesis from the Coval-Shumway put-return ordering and the PPUT drag: deeper-OTM long wings have the lowest expected return per rupee of premium, so a very far wing is the costliest hedge per unit, but the cheapest in absolute rupees.
3. **Compare against naked short puts / unhedged strangle at equal margin or equal risk, not equal lots.** Since no paper retrieved compares them, this comparison is the main experiment. Bondarenko's PUT-index drawdown (32.7% vs 50.9% for the S&P 500) is for cash-secured ATM writing and says nothing about defined-risk spreads.
4. **Use a risk measure beyond Sharpe.** Bondarenko's own caution about skewness: add max drawdown, worst-month loss, CVaR/expected shortfall, and a block-bootstrap confidence interval on mean P&L (BCJ's sampling-error argument).
5. **Put side vs call side asymmetry.** Coval-Shumway and CJP/CJS treat calls and puts differently (CJP's violations are in calls; the put premium is where crash compensation sits). Test the put wing and call wing separately: sell asymmetric condors (e.g. closer short put vs further short call, or the reverse) and check whether the call side adds premium with less tail exposure. Caveat: the evidence is US S&P 500; the Nifty skew is unlikely to be identical.
6. **Do not rely on a straddle/ATM premium as evidence of safe harvest.** Coval-Shumway's -3%/week for zero-beta straddle buyers implies sellers earn the premium on average, but the priced-volatility-factor interpretation means losses cluster in volatility spikes. For the ATM-body of a BWB or condor, add a VIX-spike gate and test its effect on drawdown; the repo already has a VIX gate, so report its marginal value.
7. **Execution costs.** CJP/CCP results are stated net of bid-ask, but the repo's BS-priced backtest has no bid-ask and the real-price chain engine shows negative expectancy (-177/-238/-348 Rs/lot at 1.0x/1.5x/2.0x slippage per CLAUDE.md). Far-OTM wings usually have the widest relative spreads, so test wing-cost sensitivity separately at 1x/1.5x/2x slippage (my note: this is a hypothesis; no retrieved source quantifies wing spreads).
8. **Hold-to-expiry vs early exit.** The papers study holding to expiry (returns per period). Run the condor/BWB both ways, because the exit rules (50% profit target, 2x credit stop) change the payoff distribution and thereby the reading of "premium harvested".
9. **Sample-split discipline.** Report results by year and by regime, and never accept a result that disappears when one crash year is removed (BCJ Peso-problem logic; CJS sample-version sensitivity).

Caveats: abstract-level evidence only; all studies are US index options (S&P 500/100), mostly monthly or weekly holding periods from 1986 onward, with sample ends between 1995 and 2013; weekly Nifty expiries and retail-dominated flows are not covered by any retrieved source; the conclusions conflict on statistical significance; full-text confirmation of every number above is needed before citing in a final report.
