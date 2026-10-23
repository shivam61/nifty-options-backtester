# Open-interest effects at expiry: pinning, max pain, OI walls, expiry-day behaviour, put-call ratios

## Access and method caveat (read first)

- Full texts were NOT read for any paper below. WebFetch failed with DNS errors (`getaddrinfo ENOTFOUND`) on every host tried: ideas.repec.org, math.nyu.edu, papers.ssrn.com, arxiv.org, www.cxoadvisory.com, harbourfrontquant.substack.com. A direct `curl` through the session proxy to ideas.repec.org returned `CONNECT tunnel failed, response 403` (host not allowed for this session). The proxy README says not to route around this, so I did not try.
- Only WebSearch worked. It returns an LLM-written summary plus URLs, not the page text. Every number below is therefore from search-result summaries of abstracts, working-paper pages or secondary write-ups. "Abstract-level" means the summary quoted the abstract. "Secondary" means a blog or review.
- Nothing is filled from memory. Anything I could not source is under Gaps. Exact effect sizes, t-stats and robustness tables for the core papers were not retrievable.
- Several search results said "the age metadata was unreliable" or that a page's text belonged to a different paper (e.g. a ResearchGate page for Elms). Treat all details as "verify against the paper before citing".

## Q1. Ni, Pearson & Poteshman (2005): size of clustering, data, mechanism

### Takeaway
Abstract-level evidence says closing prices of optionable US stocks cluster at strikes on expiration dates. The authors estimate the return shift at least 16.5 bp per expiration date. They attribute it to market-maker delta-hedge rebalancing plus proprietary-trader manipulation. Single-stock, US, 1996–2002; the effect on a cash-settled index like Nifty is not addressed by this paper.

### Cited Findings
- Paper: Ni, Pearson, Poteshman, "Stock price clustering on option expiration dates", Journal of Financial Economics 78(1), 49–87, 2005. Read: abstract-level summaries only — [RePEc/IDEAS](https://ideas.repec.org/a/eee/jfinec/v78y2005i1p49-87.html) (page itself not loadable; content via search summary), [SSRN 519044](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=519044), [HKBU scholars record](https://scholars.hkbu.edu.hk/en/publications/stock-price-clustering-on-option-expiration-dates-3/).
- Core result: on expiration dates the closing prices of stocks with listed options cluster at option strike prices. Returns of optionable stocks are altered by an average of at least 16.5 basis points on each expiration date, which the abstract converts to roughly $9 billion of aggregate market capitalization — [HKBU scholars](https://scholars.hkbu.edu.hk/en/publications/stock-price-clustering-on-option-expiration-dates-3/), [CXO Advisory summary](https://www.cxoadvisory.com/equity-options/stock-price-pinning-at-options-expiration).
- Mechanism stated in the abstract: hedge rebalancing by option market makers and stock price manipulation by firm proprietary traders both contribute — [HKBU scholars](https://scholars.hkbu.edu.hk/en/publications/stock-price-clustering-on-option-expiration-dates-3/).
- Data (from the 2003 preprint, per a search summary; not verified): OptionMetrics data 1996–2002 and CBOE investor-category statistics; 184,449 optionable stock-expiration pairs was reported by the summary, but the same summary garbled a related "80 expiration dates" figure, so treat both as unverified — [OptionMetrics research page](https://optionmetrics.com/?p=1084).
- Stocks are more likely to close near a strike on expiration dates than on other days, and the effect is tied to optionable stocks — [Zhang-Chen-Cai weekly-options paper, wpunj.edu](https://www.wpunj.edu/Weekly%20Options%20on%20Stock%20Pinning%20upto%20page%208.pdf) (secondary description of NPP).
- Dealer-positioning dependence (follow-up using CBOE position data): pinning frequency is much higher when market makers are net long options than when they are net short; a hedging story only works with net-long dealers (they buy dips and sell rallies around the strike) — [Zhang-Chen-Cai](https://www.wpunj.edu/Weekly%20Options%20on%20Stock%20Pinning%20upto%20page%208.pdf); consistent with the Avellaneda–Lipkin assumption of net-long market makers in [Avellaneda et al. PowerLaw.pdf](https://math.nyu.edu/inmemoriam/avellaneda/PowerLaw.pdf).
- Manipulation vs hedging remains unresolved: a press report quoted a former SEC economist saying evidence is "consistent with manipulation but does not prove it" (said about the related Ni-Pearson-Poteshman-White paper) — [GlobalCapital](https://www.globalcapital.com/article/28mssnrew086objkx3ic3/derivatives/study-says-options-traders-probably-manipulate-stock-prices).
- Related volatility paper: Ni, Pearson, Poteshman & White, "Does option trading have a pervasive impact on underlying stock prices?", Review of Financial Studies 34(4), 1952–1986, 2021. Finds stock return volatility is significantly negatively related to net purchased option positions of investors likely to be hedged against by market makers (net long dealer gamma lowers vol); documents a non-informational hedge-rebalancing channel — [HKBU scholars](https://scholars.hkbu.edu.hk/en/publications/does-option-trading-have-a-pervasive-impact-on-underlying-stock-p/), [RePEc](https://ideas.repec.org/a/oup/rfinst/v34y2021i4p1952-1986..html). Abstract-level only; the magnitudes were not retrieved.
- Replication note: a weekly-options replication reported that the pinning percentage "is never above 6% on the days before and after option expiration days", described as consistent with the original (secondary; the baseline pinning percentage itself was not given) — [Zhang-Chen-Cai](https://www.wpunj.edu/Weekly%20Options%20on%20Stock%20Pinning%20upto%20page%208.pdf).

### Inferences
- The 16.5 bp figure is an average lower bound across thousands of US single stocks, which is small compared with the daily range of a stock and far smaller than the distance between Nifty strikes (50 or 100 points = roughly 0.2–0.4% of spot at ~25,000 — my arithmetic, not from a source). It does not by itself justify placing short strikes at OI walls.
- The hedging story needs dealers net long options. In Indian index options, retail traders are widely reported to be net buyers and writers (proprietary firms, FIIs) net sellers, so dealer sign in India is likely the reverse of the US pinning condition. That is an inference; I found no source on dealer sign in NSE index options.

### Gaps
- Exact pinning probabilities by open-interest bucket, t-statistics and robustness tests of NPP 2005: not retrievable (full text unavailable).
- Whether pinning appears for cash-settled European index options: NPP studies single stocks (physically settled American options), so not covered.

## Q2. Avellaneda & Lipkin (2003), Golez & Jackwerth (2012) and later pinning work

### Takeaway
Avellaneda–Lipkin is a theory (hedging by net-long market makers can pull a stock to a high-OI strike with finite probability). Golez–Jackwerth give the main index-level evidence: S&P 500 futures are pulled toward the at-the-money strike on serial-option expiry days, with "anti-cross-pinning" before index option expiry. A recent working paper (Elms, not peer reviewed) finds no pinning in 2016–2025, which suggests decay.

### Cited Findings
- Avellaneda & Lipkin, "A market-induced mechanism for stock pinning", Quantitative Finance 3(6), 417–425, 2003. Read: abstract/summary level — [author page](https://math.nyu.edu/~avellane/stock_pinning.html), [PDF](https://math.nyu.edu/inmemoriam/avellaneda/qf3601.pdf) (not loadable; summary via search).
  - Model: stock SDE with a singular drift representing hedging price impact; pinning has finite (not certain) probability; probability depends on volatility, time to maturity, open interest and a price-elasticity constant. Market makers long gamma buy below and sell above the strike — [author page](https://math.nyu.edu/~avellane/stock_pinning.html).
  - Critique: Jeannin, Iori & Samuel (2006) note the model assumes perfectly liquid markets and ignores feedback effects — [Iori slides](https://rf.mokslasplius.lt/vilnius-2006-cost-p10/May_14_Sunday/9_Giulia_Iori.pdf).
  - Follow-up (Avellaneda, Kasyan, Lipkin) assumes open interest large relative to average stock volume and net-long market makers — [PowerLaw.pdf](https://math.nyu.edu/inmemoriam/avellaneda/PowerLaw.pdf).
- Golez & Jackwerth, "Pinning in the S&P 500 futures", JFE 106(3), 566–585, 2012. Read: abstract-level — [SSRN 1664261](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1664261), [RePEc](https://ideas.repec.org/a/eee/jfinec/v106y2012i3p566-585.html), [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0304405X12001365).
  - S&P 500 futures are pulled toward the at-the-money strike on days when serial options on S&P 500 futures expire (pinning).
  - Futures move away from the cost-of-carry-adjusted at-the-money strike shortly before index option expiry ("anti-cross-pinning").
  - Mechanism: delta-hedge rebalancing by market makers responding to time decay, plus reselling and early exercise of in-the-money options by individual investors.
  - Size: notional futures shift of at least $115 million per expiration day. (Futures market, where hedging occurs; index options in the paper are cash-settled.)
  - I could not retrieve sample dates, strike-distance statistics or t-stats. A later paper says Golez–Jackwerth documented pinning "through 2009" (secondary) — [Elms summary](https://harbourfrontquant.substack.com/p/from-pinning-to-amplification-evidence).
- Weekly options and stock pinning: Zhang, Chen & Cai (2015), "Weekly Options on Stock Pinning" (working paper). Since June 2010 CBOE has listed weekly options on some stocks. They find pinning remains pervasive on monthly expiration days, but weekly options differ from monthly ones. Clustering is strongest for weeklies with high volume and a large strike grid. They tie results to both the delayed-delta-hedge and manipulation hypotheses — [wpunj.edu PDF](https://www.wpunj.edu/Weekly%20Options%20on%20Stock%20Pinning%20upto%20page%208.pdf). Secondary description; magnitudes not retrieved.
- Recent contrary evidence (decay): Elms, "From Pinning to Amplification: Evidence of a Regime Shift in S&P 500 Options Expiration Dynamics, 2016–2025", SSRN 6564078 (working paper, not peer reviewed). Five tests find no evidence of pinning. The one significant result (p < 0.001) is that days with the highest at-the-money open interest had 16% wider daily ranges than days with the lowest. Sample: about 1.6 million near-expiry SPY option records over 2,294 trading days, matched to E-mini futures at one-minute resolution. The author calls the regime shift a hypothesis — [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6564078), [Harbourfront summary](https://harbourfrontquant.substack.com/p/from-pinning-to-amplification-evidence). Abstract-level.
- Gamma and intraday momentum/reversal: Barbon & Buraschi, "Gamma Fragility" (working paper; 300 underlying stocks and indexes with the largest average dollar open interest, 1996–2017 per press coverage). Negative ex-ante dealer gamma imbalance plus illiquidity leads to intraday momentum, positive leads to reversal; flash crashes are more likely and larger on negative-gamma days — [author page](https://abarbon.com/papers/gamma-fragility), [AFA abstract](https://afajof.org/management/viewp.php?n=129472), [SpotGamma coverage (vendor)](https://spotgamma.com/wall-street-dealers-in-hedging-frenzy-get-blamed-for-volatility/). Contested: a 2026 Princeton senior thesis on 0DTE found the hedging-feedback channel adds no meaningful predictive power for intraday variance — [Princeton thesis record](https://theses-dissertations.princeton.edu/entities/publication/61115cd1-cb09-4a8b-9230-ff488fc2a386) (student thesis, weak source).
- 0DTE impact: Amaya, Garcia-Ares, Pearson & Vasquez, "0DTE Index Options and Market Volatility: How Large is Their Impact?" (Jan 2025 version): estimates the maximum effect of market-maker gamma on index volatility using proprietary trade data; the search summary did not retrieve numerical conclusions — [Cboe-hosted PDF](https://cdn.cboe.com/resources/education/research_publications/gammasqueezes.pdf). A Cboe blog (exchange-authored, interested party) reports net gamma exposure of $170mm to $670mm intraday, 0.04% to 0.17% of daily S&P futures liquidity — [Cboe Insights](https://www.cboe.com/insights/posts/volatility-insights-evaluating-the-market-impact-of-spx-0-dte-options). Adams, Fontaine, Ornthanalai also study this ("Do S&P 500 options increase market volatility? Evidence from 0DTEs") — [PDF](https://www.jean-sebastienfontaine.com/papers/0dte-options-volatility.pdf); results not retrieved.

### Inferences
- Pinning evidence is strongest for single stocks (1996–2002) and S&P futures (to roughly 2009). Evidence for index options after the weekly/0DTE expansion is mixed to negative (Elms). A weekly-expiry Nifty strategy is in the post-weeklies regime, so decay risk applies.
- If the Elms finding is right (higher ATM OI associated with 16% wider ranges, not pinning), OI concentration near spot would argue for wider, not tighter, short strikes on those days. This rests on one unreviewed working paper.
- Anti-cross-pinning in Golez–Jackwerth means the price may be pushed away from the ATM strike just before expiry, which is opposite to naive "pin" use.

### Gaps
- Magnitudes, sample years, and robustness for Golez–Jackwerth and Avellaneda–Lipkin empirics: not retrievable.
- No study found of pinning in NSE index options or stock options (searches returned only Indian volatility-at-expiry studies; see Q5).
- Ni-Pearson-Poteshman-White findings on index-level expiry effects: not retrieved.

## Q3. Max pain: rigorous tests vs retail/blog claims

### Takeaway
The only rigorous test I found is Filippou, Garcia-Ares & Zapatero, "No Max Pain, No Max Gain" (SSRN working paper, US stocks), which finds a cross-sectional long-short stock return effect driven by reversals in small illiquid stocks. I found no peer-reviewed test that max pain predicts an index closing level, and no rigorous test on Nifty. The "60–70% accuracy" claim is unsourced vendor text.

### Cited Findings
- Filippou, Garcia-Ares & Zapatero, "No Max Pain, No Max Gain: A Case of Predictable Reversal" (SSRN 4140487, June 2022; later retitled "Stock Price Predictability at Options Expiration"). Abstract-level only — [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4140487), [author blog](https://pedrogares.wordpress.com/2022/08/18/no-max-pain-no-max-gain-stock-price-predictability-at-options-expiration/), [EconBiz](https://www.econbiz.de/Record/no-max-pain-no-max-gain-stock-return-predictability-at-options-expiration-filippou-ilias/10013405282).
  - Test: long-short portfolios on a max-pain measure (long high-max-pain, short low-max-pain stocks); decile portfolios formed on the second Friday of each month and held one week (secondary write-up). The abstract reports excess risk-adjusted returns.
  - Magnitude: secondary sources give average weekly long-short return about 0.4% and a sample of US stocks and options 1996–2021; these are secondary and not verified against the paper.
  - Source of the effect: mostly reversals in stocks that had fallen sharply beforehand; stronger in small, illiquid stocks; authors suggest manipulation may explain why reversals start near expiry. Higher abnormal volume and order imbalances in high max-pain portfolios (author site).
  - Honest reading: this is a cross-sectional single-stock return predictor (the paper's "max pain" is a stock-level measure relative to price), not evidence that an index settles at its max-pain strike.
- Retail/vendor claims (low quality): Strike.money states max pain aligns with the actual expiry price "around 60–70% of the time" in liquid markets like Nifty 50 or S&P 500 and names no study — [Strike.money](https://www.strike.money/options/max-pain-options). Other broker pages (StockCalc, 5paisa, Upstox, optioncharts) describe calculation only; the same-day max-pain level for one expiry differed across sites (22,850 vs 22,600), so a backtest needs time-stamped snapshots — see search outcome summarised in [StockCalc](https://stockcalc.in/calculator/options-max-pain) and [5paisa](https://www.5paisa.com/blog/nifty-weekly-expiry-13-october-2026-22500-key-support-options-trading). A Substack "max pain theory in practice" post exists but could not be opened — [Harbourfront](https://harbourfrontquant.substack.com/p/max-pain-theory-in-practice). None of these report a baseline-controlled test.
- A Scribd upload claiming "99.2% correlation between the highest-OI strike and next-day Nifty close" — [Scribd](https://www.scribd.com/document/757977203/PCR-ANALYSIS) is an unverified document. Correlation of two price-level series says nothing about predictive power (both track spot). Discard.

### Inferences
- A 60–70% "hit rate" is meaningless without defining a hit (distance band) and a baseline. With 50-point strikes and a narrow band, a random strike near spot would also "hit" often, since max pain is almost always near spot.
- Because max pain is computed from the same OI that is concentrated around ATM strikes, any test must compare against a naive "close = prior close / ATM strike" benchmark.

### Gaps
- No peer-reviewed or rigorous test of max pain for index options located.
- Full results of Filippou et al. (alphas, t-stats, transaction-cost survival) not retrievable.

## Q4. Put-call ratio predictive power

### Takeaway
The strongest evidence is Pan & Poteshman (2006): PCRs built from buyer-initiated open-to-new-position volume predict single-stock returns (low-PCR stocks outperform high-PCR by more than 40 bp next day, more than 1% next week). That signal needs signed, opening-trade data, which public EOD volume/OI does not give. Index-level PCR evidence is weak, short-sample or mixed; the Indian study finds OI-PCR predictive over about 12 days (2001–2013) but conflicts exist in how the MDPI result is summarised.

### Cited Findings
- Pan & Poteshman, "The information in option volume for future stock prices", Review of Financial Studies 19(3), 871–908, 2006. Abstract-level — [NBER w10925](https://www.nber.org/papers/w10925), [OptionMetrics page](https://optionmetrics.com/research/j-pan-and-a-m-poteshman-the-information-in-option-volume-for-stock-prices/).
  - Data: CBOE proprietary data identifying buyer-initiated option volume to open new positions; single stocks (not index); US.
  - Result: on a risk-adjusted basis, stocks with low put-call ratios outperform stocks with high ratios by more than 40 bp the next day and more than 1% over the next week.
  - Source: non-public information held by option traders rather than market inefficiency; stronger for stocks with more informed trading and for higher-leverage contracts.
  - A later study on Taiwan options (summary) found that predictability of a publicly observed put-call ratio is insignificant while a non-public version contained information — [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0927538X25000241). Important: signal quality depends on opening/buyer-initiated classification that public data lack.
- Blau & Brough (2015), "Are put-call ratios a substitute for short sales?", Review of Derivatives Research 18(1), 51–73: put-call ratios move inversely with proxies for short-sale constraints; the negative relation between current PCR and future returns holds regardless of short-sale constraints; PCRs tend to follow negative-return periods and predictability comes from ratios that follow positive returns. Abstract-level — [RePEc](https://ideas.repec.org/a/kap/revdev/v18y2015i1p51-73.html). Counter-view: Grundy, Lim & Verwijmeren (2012) and Chen, Chou & Lin (2020) find bearish option volume partly substitutes for shorting — [EUR repository](https://repub.eur.nl/pub/38949), [NCCU](https://irtest.lib.nccu.edu.tw/handle/140.119/128719). Single-stock.
- Bandopadhyaya & Jones (2008), "Measures of investor sentiment: a comparative analysis, put-call ratio vs. volatility index", Journal of Business & Economic Research 6(8). Full text available at the journal but not read; abstract only. Daily data 2 Jan 2004 to 11 Apr 2006; the PCR was a better explanatory variable than VIX for variation in the S&P 500 not explained by economic factors. This is a contemporaneous explanation test over about 2.3 years, not an out-of-sample forecast — [Cluteinc journal page](https://clutejournals.com/index.php/JBER/article/view/2458).
- Billingsley & Chance (1988), "Put-call ratios and market timing effectiveness", Journal of Portfolio Management (the search tool flagged the user's assumed venue "Financial Analysts Journal" as wrong). Only secondary claims found: extreme PCR values treated as contrarian indicators; one site's "68% reversal within a month" is unverified; another study cited found PCRs have practically no predictive power — [Strike.money](https://www.strike.money/?p=5999). Original not located; findings unverified.
- Jena, Tiwari & Mitra (2019), "Put–Call Ratio Volume vs. Open Interest in Predicting Market Return: A Frequency Domain Rolling Causality Analysis", Economies 7(1), 24. NSE (Nifty) daily data June 2001 to May 2013. Volume PCR is an efficient predictor of market return over about 2.5 days and OI-PCR over about 12 days; results robust to controlling for futures-market information — [MDPI](https://www.mdpi.com/2227-7099/7/1/24), [IDEAS](https://ideas.repec.org/a/gam/jecomi/v7y2019i1p24-d217055.html). Conflict: one search summary of the same MDPI paper said volume PCR does not have predictive power while OI-PCR Granger-causes returns over longer horizons (about 12 days and above) — the two summaries disagree on volume PCR; full text needed. Method is causality in the frequency domain, with no trading rule, no costs and no out-of-sample test.
- Other index-level: a study of S&P 500 and Romanian BET found no significant connections or causality between PCR and either index, with the authors noting reliance on linear VAR may have affected results — [IDEAS](https://ideas.repec.org/a/agr/journl/vxxxiiy2025i1(642)p187-210.html). A Koch white paper (Wall Street Courier, 2007–2022 CBOE PCR): useful contrarian indicator at extreme negative sentiment; sell signals weak and underperformance after low ratios was not statistically significant — [Wall Street Courier](https://www.wallstreetcourier.com/spotlights/the-cboe-put-call-ratio-a-useful-greed-fear-contrarian-indicator/) (white paper, not peer reviewed).
- Taiwan option-writing paper, "Low risk, high return: improving option writing performance with put-call ratios in Taiwan" (ScienceDirect, 2025): title claims PCR improves option-writing results, but I did not retrieve details — [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0927538X25000241). Potentially the most directly relevant paper for a PCR gate on short-option strategies; flagged for follow-up.

### Inferences
- Pan–Poteshman's edge comes from signed opening volume on single stocks. The Nifty archive provides settle, OI and volume per strike, not signed opening volume, so that signal cannot be replicated; OI-based PCR is a different, weaker quantity.
- Contrarian vs momentum interpretation is horizon- and definition-dependent: Pan–Poteshman is negative (low PCR is bullish, i.e. informed-flow interpretation), the CBOE white paper is contrarian at extremes. These two are not the same thing and should not be combined in one rule without testing.
- For a short-premium strategy the relevant question is vol/tail prediction, not direction. I found no study that tests PCR against subsequent index volatility or weekly range.

### Gaps
- Exact effect sizes/t-stats for Bandopadhyaya & Jones, Billingsley & Chance, Jena et al.: not retrieved.
- No Nifty PCR study after 2013 and no out-of-sample or cost-inclusive test found.
- No source tests PCR against subsequent realised or implied volatility for index options.

## Q5. Expiry-day effects on index volatility and returns, weekly expirations, concentration

### Takeaway
Indian studies are mixed and mostly pre-2020 or low-profile. US evidence says 0DTE/weekly gamma impact is small per exchange-affiliated work, with academic work (Barbon–Buraschi) finding intraday momentum/reversal tied to dealer gamma. I found no high-quality, post-2019 peer-reviewed study of Nifty weekly-expiry-day returns.

### Cited Findings
- Indian expiry-day studies (search-summary level; quality varies):
  - Some studies report higher returns and volatility on expiry days than other days; one Nifty study found spot volatility increased on expiry days and weeks after F&O introduction; an older GARCH study found a significant volatility increase on expiry days but less relative volatility during expiration week — [Journal of Management and Science PDF](https://pdfs.semanticscholar.org/4250/1850c7186cb41b0289e4d173acf7ade3b58d.pdf), [ResearchGate: Expiry day impact on return NSE](https://www.researchgate.net/publication/339949132_Expiry_day_Impact_on_return_on_Indian_Stock_market_NSE-_an_Empirical_Study).
  - Weekly options: a study of the 2019 Nifty weekly-expiry launch found a significant decrease in the association of market returns and volatility — [Academia: Effect of the launch of Nifty weekly options on Nifty and India VIX](https://www.academia.edu/66109576/Effect_of_the_Launch_of_Nifty_Weekly_Options_on_the_Relationship_between_Nifty_and_India_VIX). A Bank Nifty study compares 74 expiry dates split evenly before/after weekly options from April 2013 — [KoreaScience](https://koreascience.kr/article/JAKO202032462596875.view?orgId=kodisa).
  - A sectoral-index study found no volatility effect and no price reversal after expiry — same Journal of Management and Science PDF above.
  - A Zenodo paper argues weekly expiry days show higher intraday volatility in the last trading hours, stronger for Bank Nifty, but it says it uses a simulated dataset, so do not use its magnitudes — [Zenodo](https://zenodo.org/records/19220278).
  - Springer (2025), "Effect of multiple index derivative expiry on volatility, volume, and connectedness: a tale of two stock indices in India" — exists but results not retrieved — [Springer](https://link.springer.com/article/10.1007/s11147-025-09221-8).
- US: CBOE weeklies for stocks (June 2010) shifted pinning from monthly to weekly; see Q2 (Zhang–Chen–Cai). Todorov, "Short-term market risks implied by weekly options" studies SPXW risk-neutral dynamics, not pinning — [Kellogg PDF](https://www.kellogg.northwestern.edu/faculty/todorov/htm/papers/wo.pdf).
- Expiry-day volatility from hedging: Ni–Pearson–Poteshman–White (2021) and Barbon–Buraschi (see Q1, Q2).

### Inferences
- An expiry-day range gate on Nifty is testable from the archive's own spot/settle series, so no outside source is needed.
- The 2025-09-01 cutover (Thursday to Tuesday) splits the sample into two regimes, which the project's CLAUDE.md already records.

### Gaps
- No rigorous post-2019 study of Nifty/Bank Nifty weekly-expiry return/volatility effects found.
- Expiry-day concentration of volume/OI at NSE: not found beyond blog commentary.
- SEBI/NSE regulatory studies on expiry-day behaviour: not searched successfully.

## Implications for a Nifty backtester

### Takeaway
No source supports a rule of placing short strikes beyond OI walls or at max pain. Mechanistic evidence for pinning exists for US single stocks (to 2002) and S&P futures (to about 2009), is decaying or reversed in the most recent index-options sample (one unreviewed paper), and depends on dealer sign, which is likely the opposite of the pinning condition in Nifty weeklies (retail net buyers). PCR evidence relies on signed opening volume that the archive lacks. Treat all three as hypotheses to test, with low prior.

### Evidence strength by candidate rule
| Rule | Evidence | Strength |
|---|---|---|
| Short strikes beyond highest-OI call/put strike (OI walls as barriers) | None found in literature; only vendor and broker text. Hedging mechanism gives pull toward, not repulsion from, the strike | Unsupported |
| Max-pain as expected settlement | No rigorous index test; vendor 60–70% claim unsourced; one stock-level cross-sectional paper | Unsupported for index |
| Pinning toward high-OI strike on expiry day | NPP (single stocks), Golez–Jackwerth (S&P futures), weak/negative recent evidence (Elms) | Weak, decaying |
| High ATM OI means wider expiry-day range | Elms: 16% wider daily range, p < 0.001, SPY, one working paper | Single unreviewed paper |
| OI-PCR or volume-PCR gate | Jena et al. (Nifty 2001–2013, 12-day OI-PCR horizon); mixed elsewhere | Weak, dated |
| Expiry-day volatility gate | Mixed Indian studies | Weak |

### Concrete testable rules using only EOD strike, settle, OI and volume
Pre-register each; report against a naive baseline and use the project's slippage multipliers (1.0x/1.5x/2.0x) as in the chain engine.
1. OI-wall pin test (descriptive). For every weekly expiry, compute at the last EOD before expiry: highest-call-OI strike, highest-put-OI strike, max-pain strike (minimise total writer payout using OI x intrinsic at settle prices). Measure |expiry settle minus level| in points and as multiples of the strike step. Baseline: |settle minus prior close| and |settle minus nearest-ATM strike|. Report the hit rate within one strike step against a placebo of random strikes with the same distance from spot. This replicates the NPP clustering idea (does the settle land closer to high-OI strikes than chance?) in a way that is falsifiable.
2. OI-wall barrier test. For each expiry, bucket by whether the short strike is inside or beyond the OI wall; compare P&L, breach frequency and tail loss per lot. Also regress breach on strike distance in standard deviations (VIX-implied) with OI-wall-beyond as an extra dummy, so the effect is measured after controlling for distance.
3. ATM-OI concentration vs range. Elms-style: sort expiry days into terciles by ATM OI share of total OI and compare realised close-to-close / high-low range. Prediction from Elms is wider range at high ATM OI; prediction from pinning is narrower. Settle which holds on Nifty.
4. PCR gate. Compute OI-PCR (total put OI / total call OI) and volume-PCR from the archive at the entry date. Test: forward 5- and 12-trading-day Nifty return and realised range in PCR quintiles (Jena et al. horizons), with Newey–West errors, then as a gate (skip or widen when PCR is extreme). Use rolling-origin evaluation, because the published evidence is in-sample and ends in 2013.
5. Expiry-day rule. Compare outcomes of positions held through expiry day against closing at the previous session, split by weekday-era (Thursday to 2025-08-28, Tuesday from 2025-09-02) and by the 19 holiday-shifted expiries.

### Failure modes
- Look-ahead: max pain, OI walls and PCR must be taken from the last EOD snapshot before the decision; intraday OI is not in the archive.
- Dealer sign unknown: the archive has no buyer/seller classification, so the pinning mechanism cannot be conditioned on dealer position.
- Option settlement: Nifty is cash-settled European, unlike US single-stock options, which are physically settled with early exercise.
- Strike grid: wide Nifty strike spacing makes "near a strike" hits likely by chance; use the placebo above.
- OI ≈ ATM clustering: max pain and highest OI are nearly always near spot, so rules based on them will mostly re-encode spot distance.
- Multiple-testing and regime change: weeklies, the 2025 expiry-day move, 0DTE growth and SEBI contract changes alter OI composition.
- EOD marks: the archive has no bid/ask; the project's own chain-engine result already shows negative expectancy for model-free short-premium baselines, so any filter must be judged against that baseline, not against zero.

### Gaps
- No Nifty-specific peer-reviewed test of OI walls, max pain or PCR for short-option strike selection was found.
- Full texts of all core papers should be read by someone with access to RePEc/SSRN/ScienceDirect (blocked here) before anything above is cited as an effect size.
- Not searched: SEBI/NSE research notes on expiry-day behaviour, Bank Nifty-specific OI studies, and "Low risk, high return" Taiwan PCR option-writing paper details.
