# Option demand pressure, order flow, dealer positioning and dealer gamma: what they imply for option prices, volatility and index dynamics

**READ-STATUS WARNING (applies to every paper below).** No full text was read. `WebFetch` failed with `getaddrinfo ENOTFOUND` on every domain tried (www3.nd.edu, academicweb.nd.edu was never fetched directly, www.nber.org, papers.ssrn.com, pure.eur.nl, alphaarchitect.com, causalclaims.trfetzer.com, arxiv.org, dspace.kaist.ac.kr, www.mit.edu, econpapers.repec.org). A Bash attempt to read the proxy status was denied by the permission classifier and was not worked around. All content comes from `WebSearch` result summaries, which are abstracts, citing papers, or blogs. Every number below is quoted from those summaries. Table-level numbers (t-stats, R2, coefficients) are mostly missing and are marked as gaps. Verify against the PDFs before relying on any figure. Several PDFs were located (URLs listed per paper) and can be fetched where network access works.

---

## 1. Demand pressure in option prices: Bollen & Whaley (2004) and Garleanu-Pedersen-Poteshman (2009)

### Takeaway
Both papers say customer net demand moves option prices and implied-volatility shape, because dealers cannot hedge or arbitrage away the order imbalance. Bollen-Whaley is evidenced on S&P 500 and single-stock options from daily signed volume. GPP needs end-user vs dealer position data and finds index options expensive because end users are net long OTM puts. Neither can be rebuilt from EOD OI/volume alone. Out-of-sample replication on KOSPI200 contradicts Bollen-Whaley's daily result.

### Cited Findings

**Bollen & Whaley (2004)**
- Record: Bollen, N.P.B. and Whaley, R.E., "Does Net Buying Pressure Affect the Shape of Implied Volatility Functions?", Journal of Finance 59(2), 711-753, 2004. [Wiley DOI page](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.2004.00647.x); [SSRN 319261](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=319261). READ: abstract-level and citing-paper summaries only (full text NOT read).
- Market: S&P 500 index options and individual-stock options (US). Sample period, frequency details and sample size were not in the retrieved summaries (gap). Daily data per the secondary description below.
- Measure: "net buying pressure" = number of buyer-motivated contracts minus seller-motivated contracts, multiplied by the absolute value of the option's delta (as described by a citing paper's summary) — [Borsa Istanbul Review / search summary, Ryu et al. 2022](https://doaj.org/article/753dac9e1fa44fd3947a8c20c42ecdf1); description of the measure via [XJTLU abstract of an NBP/IV paper](https://scholar.xjtlu.edu.cn/en/publications/investors-net-buying-pressure-and-implied-volatility-dynamics/). Signing uses trade classification (buyer- vs seller-motivated), which needs trade-level data with quotes.
- Finding: changes in implied volatility are directly related to net buying pressure from public order flow; S&P 500 option implied vol changes are most strongly affected by buying pressure for index puts, while stock option implied vol is dominated by call demand — [Wiley/search summary](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.2004.00647.x).
- Explanation: limits to arbitrage make the option supply curve upward sloping so implied vol relates to net buying pressure; simulated delta-neutral option-writing strategies earn abnormal returns that match the deviations of the implied vol functions above realized historical return volatilities — same source.
- Effect sizes, t-stats, robustness: NOT retrieved (gap).
- Replication/conflict: Kang and Park (KAIST) tested KOSPI200 options and report that the Bollen-Whaley net buying pressure hypothesis "does not hold in the daily data", attributing this to directional rather than volatility-focused traders (supports the learning hypothesis over limits-of-arbitrage) — [KAIST dspace](https://dspace.kaist.ac.kr/handle/10203/5421) (search summary only, not opened).
- Replication/conflict: a study of ETF and index options reports results "inconsistent with the argument of Bollen and Whaley (2004) that an option's implied volatility function should be positively related to its net buying pressure" — [SJSU ScholarWorks](https://scholarworks.sjsu.edu/cgi/viewcontent.cgi?article=1062&context=acc_fin_pub) (summary only).
- Extensions: Ryu, Webb, Yang and Yu (Borsa Istanbul Review, 2022) extend Bollen-Whaley with hedging demand for futures, intraday seasonality and dynamic effects — [DOAJ](https://doaj.org/article/753dac9e1fa44fd3947a8c20c42ecdf1). A VIX-options study finds a temporal relationship between NBP and changes in implied vol of vol, consistent with limits to arbitrage — [vLex](https://law-journals-books.vlex.com/vid/the-impact-of-net-855682127).

**Garleanu, Pedersen & Poteshman (2009)**
- Record: Garleanu, N., Pedersen, L.H., Poteshman, A.M., "Demand-Based Option Pricing", Review of Financial Studies 22(10), 4259-4299, 2009 (DOI 10.1093/rfs/hhp005; NBER WP 11843). [NBER](https://www.nber.org/papers/w11843); [SSRN 676501](https://papers.ssrn.com/abstract=676501); [PDF copy](https://haas.berkeley.edu/wp-content/uploads/DBOP.pdf). READ: abstract and search summaries only (full text NOT read).
- Model prediction: demand pressure in one option raises its price by an amount proportional to the variance of the unhedgeable part of the option, and raises other options' prices in proportion to the covariance of the unhedgeable parts — [Econbiz/search summary](https://econbiz.de/Record/-/10003887031).
- Data and finding: dataset of dealer and end-user positions (CBOE-based, per the summary). End users are net long index options, especially OTM puts, which helps explain index option expensiveness and the smirk. Equity options do not appear expensive on average and have small negative end-user demand — [AQR summary](https://www.aqr.com/Insights/Research/Journal-Article/DemandBased-Option-Pricing). An early version reports most net demand comes from puts and that, unlike in index options, equity-option end users are net suppliers — search summary of [NBER WP](https://www.nber.org/system/files/working_papers/w11843/w11843.pdf).
- Effect sizes, t-stats, sample dates, robustness: NOT retrieved (gap).
- Scope: index (S&P 500) and single-stock, US, positions data (daily/monthly frequency not confirmed).

### Inferences
- Demand-pressure effects on shape (skew) are conceptually the strongest, longest-standing literature, but the measurable object is signed, open/close-tagged flow, which public EOD data does not contain.
- The KOSPI200 and ETF/index-option counter-evidence suggests the Bollen-Whaley daily NBP result is market- and sample-dependent. Whether Nifty behaves like S&P or like KOSPI200 is untested here.

### Gaps
- No exact coefficients, t-statistics, R2, sample period for either paper (full text unreachable).
- No Indian-market replication of either paper was found.

---

## 2. Informed order flow: Pan & Poteshman (2006) and related open-buy/open-sell work

### Takeaway
Pan-Poteshman show that put-call ratios built only from buyer-initiated opening volume (needs CBOE open-close data) predict next-day and next-week stock returns, and attribute it to private information. Unsigned ratios from public data also have some predictive power in a later study, but weaker in construction. This is mostly a single-stock information story, not a dealer-hedging story.

### Cited Findings
- Record: Pan, J. and Poteshman, A.M., "The Information in Option Volume for Future Stock Prices", Review of Financial Studies 19(3), 871-908, 2006. [EconPapers](https://econpapers.repec.org/RePEc:oup:rfinst:v:19:y:2006:i:3:p:871-908); [PDF](https://www.mit.edu/~junpan/volume.pdf); [SSRN 622869](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=622869). READ: abstract and search summaries only.
- Measure: put-call ratio = put buy-to-open volume / (put + call buy-to-open volume) — [search summary of RFS abstract](https://econpapers.repec.org/RePEc:oup:rfinst:v:19:y:2006:i:3:p:871-908). Data: proprietary CBOE data identifying opening vs closing and buyer vs seller initiation.
- Result: "Stocks with low put-call ratios outperform stocks with high put-call ratios by more than 40 basis points on the next day and more than 1% over the next week" — same. Predictability stronger for stocks with higher concentrations of informed traders and for more leveraged contracts. Predictability attributed to nonpublic information rather than market inefficiency.
- Market: US single-stock options (this is a cross-sectional single-stock result, not index). Sample period, t-stats not retrieved (gap).
- Unsigned ratio: a 2014 study states "while Pan and Poteshman (2006) show that signed P/C ratios, which require proprietary data, have predictive power, we find that unsigned P/C ratios, which do not require proprietary data, also have predictive power" — [Journal of Banking & Finance, "The information content of option ratios"](https://www.sciencedirect.com/science/article/abs/pii/S037842661400106X) (abstract snippet only).
- Related: Ni, Pan & Poteshman, "Volatility Information Trading in the Option Market", Journal of Finance 2008 — [Wiley](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2008.01352.x); [PDF](https://en.saif.sjtu.edu.cn/junpan/npp.pdf). Only the title and URL surfaced; contents not read (gap).
- Indian evidence: no peer-reviewed Nifty tests found. A Scribd-hosted study (Jan 2014 - Dec 2020, 1728 observations) reports a 99.2% correlation between the strike with highest OI and the next day's Nifty close — [Scribd](https://www.scribd.com/document/686192532/PCR). Not verified as peer-reviewed; a correlation of levels (spot is persistent) is not evidence of predictive power. Broker pages state PCR bands (0.8-1.0 neutral) as rules of thumb, untested — [IIFL](https://www.indiainfoline.com/markets/derivatives/put-call-ratio).

### Inferences
- The OI-based PCR on NSE is neither signed nor open/close tagged, so it is closer to the "unsigned" variant, which is the weaker object. A rising OI-PCR can reflect put writing (bullish) or put buying (bearish); the sign is ambiguous without direction.

### Gaps
- Exact t-stats and sample dates for Pan-Poteshman not retrieved.
- No index-level (SPX) result from this paper was retrieved.
- Magnitude of the unsigned-PCR effect, its sample and decay not retrieved.

---

## 3. Dealer gamma hedging and intraday dynamics: Baltussen-Da-Lammers-Martens (2021), Barbon-Buraschi, Ni-Pearson-Poteshman-White

### Takeaway
Three papers argue that hedging flows of option dealers (and leveraged ETFs) move the underlying: negative dealer gamma amplifies (momentum, higher volatility), positive gamma dampens. All three need either dealer gamma estimated from signed positions or a proxy built from OI under assumptions. Evidence is peer-reviewed for Baltussen et al. (JFE) and Ni-Pearson-Poteshman-White (working paper per sources retrieved); the Barbon-Buraschi paper was a working paper in the sources retrieved.

### Cited Findings

**Baltussen, Da, Lammers & Martens (2021)**
- Record: "Hedging demand and market intraday momentum", Journal of Financial Economics 142, 377-403, 2021. [Full text PDF (Notre Dame)](https://academicweb.nd.edu/~zda/intramom.pdf); [SSRN 3760365](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3760365); [Erasmus repository](https://pure.eur.nl/en/publications/hedging-demand-and-market-intraday-momentum/). READ: abstract and secondary summaries only; the PDF URL surfaced but could not be fetched.
- Sample/measure: intraday returns on more than 60 futures across equities, bonds, commodities and currencies, 1974-2020. Return in the last 30 minutes is predicted by the return earlier in the day, and the predictability reverses over following days — [Erasmus abstract via search](https://pure.eur.nl/en/publications/hedging-demand-and-market-intraday-momentum/).
- Mechanism: gamma hedging by market makers of options and leveraged ETFs; hedging short gamma means trading in the direction of price moves. The effect is stronger on days when hedging flows are larger — search summaries of the JFE abstract.
- A secondary summary reports annualized Sharpe ratios of a simple momentum strategy between 0.87 and 1.73 at the asset-class level — [Alpha Architect summary](https://alphaarchitect.com/hot-topic-does-gamma-hedging-actually-affect-stock-prices/) (not opened; flagged by the search tool as secondary).
- A blog summary reports, for negative-gamma days, "a coefficient of 6.63, t-statistic 4.78 and R2 of 3.58%", with positive-gamma days much smaller and insignificant. The same source discusses Nasdaq-100 futures and notes table values are multiplied by 100 (underlying coefficient about 0.0636). The search tool could not confirm these relate to the S&P 500 — [danfin.net](https://danfin.net/intraday-momentum-final-30-minutes). Low reliability: single blog, unverified against the paper.
- Gamma measure: the exact construction (how dealer gamma is inferred; which OI/volume assumption) was NOT retrieved (gap). This is the key detail for the user's data question.
- Related decay/conflict: Baltussen, Da & Soebhag, "End-of-Day Reversal" (stocks, cross-section) says the stock-level effect "cannot be explained by liquidity- or gamma-hedging effects" — [Notre Dame PDF](https://academicweb.nd.edu/~zda/EOD.pdf) (search snippet). Different object (single stocks) from index intraday momentum.
- Market scope: index and non-index futures, US-centric option data for the gamma test; international futures cover the momentum result itself (per abstract).

**Barbon & Buraschi, "Gamma Fragility"**
- Record: Barbon, A. and Buraschi, A., "Gamma Fragility" (working paper "Gamma Fragility: Asset Pricing Implications of Delta-Hedging", 2019; SSRN posted Nov 2020, revised Mar 2021; presented at FIRS June 2021). [SSRN 3725454](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3725454); [St. Gallen](https://alexandria.unisg.ch/entities/publication/b0c4de3d-74dd-4e62-b465-2d0337fe2904/full); [Mar 2021 draft](https://tashfeenomran.com/DB/Research%20Papers/Gamma%20Fragility.pdf). No journal publication was confirmed in the sources retrieved (check). READ: abstract-level summaries only.
- Claim: large aggregate dealer gamma imbalances are linked to intraday momentum (negative ex-ante gamma imbalance) and reversal (positive imbalance), amplified by illiquidity and stronger for the least liquid underlyings; distinct from information and funding-liquidity frictions; related to frequency and magnitude of flash crashes. The proxy is built from a large panel of index and equity options — [SSRN abstract via search](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3725454).
- Effect sizes, t-stats, the exact proxy formula and the sign convention (how dealer position is assumed from OI/volume): NOT retrieved (gap).
- Scope: US equities and index options (single-stock and index panel).

**Ni, Pearson, Poteshman & White (hedger gamma and volatility)**
- Record: "Does Option Trading Have a Pervasive Impact on Underlying Stock Prices?" (Pearson, Poteshman, White; some listings add Ni). [SSRN 970592](https://www.ssrn.com/abstract=970592); [OU copy](https://www.ou.edu/dam/price/Finance/CFS/paper/pdf/pearsonPoteshmanWhite.pdf). The user's brief lists "(RFS, 2021)"; the retrieved sources show it as a working paper dated February 2007 on SSRN and do not confirm RFS publication — publication venue UNVERIFIED. READ: abstract-level summaries only.
- Hypothesis/result: hedgers' rebalancing raises stock volatility when they are net writers of options and lowers it when they are net buyers. Authors report a "statistically and economically significant negative relationship between stock return volatility and net purchased option positions of investors who are likely to hedge". Main test: the gamma of the net position of likely delta hedgers has a highly significant negative relation with the underlying's absolute return; holds for large and small stocks and survives controls for volatility persistence — [SSRN abstract and search summary](https://www.ssrn.com/abstract=970592).
- Data: needs signed, open/close-tagged position data to identify "likely hedger" net positions (CBOE data, per the surrounding literature); effect size per standard deviation not retrieved (gap).
- Scope: US single stocks; not an index result.

### Inferences
- Direction is consistent across the three: short-gamma intermediaries amplify, long-gamma dampen. All rely on knowing dealer sign. That sign is the main unobservable on NSE EOD data.
- Baltussen et al. report intraday-timed effects (last 30 minutes). A daily-EOD backtest cannot test the intraday timing; it can only test same-day/next-day aggregates.

### Gaps
- Exact gamma proxy constructions in Baltussen et al. and Barbon-Buraschi, coefficients and t-stats from the original tables.
- Publication status of Barbon-Buraschi and Ni-Pearson-Poteshman-White not confirmed.
- No evidence retrieved on whether these effects exist in Nifty or any Indian index.

---

## 4. Intermediary constraints and crash-risk demand: Chen, Joslin & Ni (2019)

### Takeaway
Dealers' net short position in deep OTM SPX puts, measured from public net buy-to-open, proxies intermediary constraints and predicts market returns (a risk-premium result, not a short-horizon volatility-timing result). Needs CBOE open-close customer data.

### Cited Findings
- Record: Chen, H., Joslin, S., Ni, S.X., "Demand for Crash Insurance, Intermediary Constraints, and Risk Premia in Financial Markets", Review of Financial Studies 32(1), 228-265, 2019 (NBER WP 25573). [NBER](https://www.nber.org/papers/w25573); [NBER PDF](https://www.nber.org/system/files/working_papers/w25573/w25573.pdf); [USC PDF](https://faculty.marshall.usc.edu/Scott-Joslin/research_gco/AJK.pdf). READ: abstract and search summaries only.
- Measure: public net buy-to-open (PNBO) of deep OTM S&P 500 puts per month (net amount public investors buy to open = amount intermediaries sell); supply vs demand shocks separated via the variance premium — [search summary of NBER WP](https://www.nber.org/papers/w25573).
- Result: "A one-standard deviation decrease in PNBO is associated with a 3.4% increase in the subsequent 3-month market excess return"; strongest in 2008-09; not explained by standard predictors, tail-risk or funding measures — same. A different search result quoted roughly 2.5% for "one related measure"; the two figures are not reconciled, so quote 3.4% only with caution (conflict between secondary summaries).
- Interpretation: during tightening, intermediaries mainly hedge their own tail exposure rather than absorb higher public demand — [NBER PDF](https://www.nber.org/system/files/working_papers/w25573/w25573.pdf) (summary).
- Decay/sample dependence: a later paper (Terstegge, "Intermediary Option Pricing") reports a different sign in a more recent sample, attributed to financial-constraint shocks — [Terstegge](https://julianterstegge.com/assets/papers/intermediary_option_pricing.pdf) (snippet only).
- Sample period for CJN: NOT confirmed in retrieved sources (gap). Monthly frequency, US index options.

### Inferences
- A monthly risk-premium predictor on S&P puts is not directly usable for selecting a weekly Nifty expiry; its relevance is as a motivation for when selling premium is paid more.

### Gaps
- Sample period and robustness details; no non-US replication.

---

## 5. Practitioner GEX claims versus peer-reviewed/quasi-academic evidence

### Takeaway
Peer-reviewed or academic-style evidence on measured dealer gamma finds the sign right but the magnitude on index volatility small when dealer positions are observed. Public-OI GEX products (SpotGamma, SqueezeMetrics, vendor blogs) are marketing-grade; the one independent GEX backtest retrieved found GEX adds little once ATM implied vol is controlled.

### Cited Findings

**Academic / working-paper evidence (secondary summaries only)**
- Amaya, Garcia-Ares, Pearson & Vasquez, "0DTE Index Options and Market Volatility: How Large is Their Impact?" (Cboe-hosted PDF dated 25 Jan 2025; SSRN Feb 2025; working paper, no journal confirmed). [Cboe PDF](https://cdn.cboe.com/resources/education/research_publications/gammasqueezes.pdf); [SSRN 5113405](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5113405). Uses Cboe trade-level SPX/SPXW data, July 2020 - June 2023, to estimate the aggregate market-maker position and gamma at one-minute frequency and a GARCH-style model of one-minute S&P futures returns; the gamma effect is negative and statistically significant per a summary. Reported magnitudes (secondary): "median effect ... reduce daily realized volatility by roughly 0.08 to 0.2 percentage points" ([Quantropy summary](https://quantropy.ai/blog/dealer-gamma-exposure-and-realized-volatility)); "at most 3.3 percentage points to annualized daily volatility" ([Way of the Trader](https://wayofthetrader.com/education/futures/0dte-options-nq)). These two summaries are not the same quantity and are not reconciled — check the PDF. Note the Cboe PDF is hosted by an exchange with an interest in 0DTE products.
- Cboe's own positioning research reports net market-maker 0DTE gamma averaging 0.04% to 0.17% of daily S&P futures liquidity — [Realtime Option](https://realtimeoption.com/blog/what-0dte-share-of-volume-means); [Yahoo Finance](https://finance.yahoo.com/news/same-day-expiry-options-really-130000545.html). Exchange publication; secondary relay.
- Adams, Fontaine, Ornthanalai (Oct 2025 working paper) reportedly conclude 0DTE options reduce index volatility on average via dealer positive-gamma hedging — [SIFMA monthly metrics, Apr 2026](https://www.sifma.org/wp-content/uploads/2026/04/SIFMA-Insights-Equities-and-Options-Monthly-Metrics_April_2026.pdf) (secondary relay; paper at [Fontaine site](https://www.jean-sebastienfontaine.com/papers/0dte-options-volatility.pdf) not opened).
- A 2026 Princeton senior thesis (undergraduate, not peer-reviewed) found the hedging-feedback channel adds no meaningful predictive power for intraday variance forecasts — [Princeton DataSpace](https://theses-dissertations.princeton.edu/entities/publication/61115cd1-cb09-4a8b-9230-ff488fc2a386) (snippet). Low weight.
- Luo and Zhang (2024) on 0DTE dealer hedging and intraday mean reversion — cited via [Math & Markets](https://mathandmarkets.com/p/the-options-tail-wagging-the-stock) (blog relay; paper not located).

**Practitioner / vendor sources (NOT peer reviewed; commercial interest)**
- SqueezeMetrics white paper (GEX originator): reports high GEX associated with low subsequent SPX volatility and a widening vol distribution when GEX is below zero; quartile figures garbled in extraction — [white paper](https://squeezemetrics.com/monitor/download/pdf/white_paper.pdf). Vendor.
- SpotGamma explainers — [SpotGamma GEX](https://spotgamma.com/gamma-exposure-gex/), [support article](https://support.spotgamma.com/hc/en-us/articles/15214161607827-GEX-Gamma-Exposure-Explained-What-It-Is-and-How-SpotGamma-Uses-It). Vendor; gamma estimated from public OI with an assumed dealer sign.
- TradeEcho "SPX GEX Report: 382 gamma flip crossings" ([link](https://tradeecho.com/research/spx-gex-report)), CrossVol ([link](https://crossvol.com/en/equity/spx-gex-live/)): vendor marketing; contents not read.
- FlashAlpha backtest of SPY, 2018-2026, n = 1,972 days: GEX has a raw relationship with next-day realized volatility and modest incremental value over VIX, but "once ATM IV is added to the control set, GEX goes quiet" — [FlashAlpha](https://flashalpha.com/articles/gex-dex-vex-chex-8-year-backtest-spy-vix-control). Vendor-published but the design (controlling for IV) is the most informative test found; independent replication absent.
- A statement in retrieved material that public data cannot identify which participant holds each side of an option, so dealer gamma is estimated, not observed — search-tool synthesis, consistent with the above vendors' own sign assumptions.

### Inferences
- Where dealer positions are observed (Cboe trade data), the aggregate volatility effect looks economically small and positive-gamma damping is the dominant finding. That cuts against large-effect GEX-level marketing claims.
- GEX on public OI measures a mix of gamma level and ATM-IV/spot-proximity-to-strikes, so it is plausibly collinear with VIX; the FlashAlpha result is consistent with that.

### Gaps
- The Amaya et al. paper and the Adams et al. paper were not opened; magnitudes are secondary and conflicting.
- No independent peer-reviewed validation of OI-based GEX forecasting realized vol was found. No Indian-market GEX study found.

---

## 6. Replication, decay, conflicts and data requirements (summary table)

### Takeaway
Evidence quality drops sharply as one moves from "signed, open-close data" (strong academic) to "public OI-implied dealer positioning" (weak/vendor). Specific conflicts: KOSPI200 and ETF/index studies vs Bollen-Whaley; magnitudes of 0DTE dealer gamma (0.08-0.2 pp vs up to 3.3 pp); CJN measure's sign differing in later samples.

### Cited Findings
| Paper | Data needed | Index or stock | Market | Full text? |
|---|---|---|---|---|
| Bollen-Whaley 2004 | signed buyer/seller-motivated volume with quotes | both | US | No |
| Garleanu-Pedersen-Poteshman 2009 | dealer vs end-user positions | both; index is where demand matters | US | No |
| Pan-Poteshman 2006 | open/close and buy/sell volume (CBOE) | stocks | US | No |
| Baltussen et al. 2021 | gamma proxy (details not retrieved) plus intraday returns | index futures + 60 futures | multi-asset 1974-2020 | No |
| Barbon-Buraschi | aggregate dealer gamma proxy (details not retrieved) | stocks + index | US | No |
| Pearson-Poteshman-White | likely-hedger net position gamma (signed) | stocks | US | No |
| Chen-Joslin-Ni 2019 | public net buy-to-open of OTM SPX puts | index | US | No |
| Amaya et al. 2025 | Cboe trade-level, one-minute | index (SPX/SPXW) | US 2020-2023 | No |
- Sample dependence: Terstegge reports a flipped sign relative to CJN in a later sample (see section 4). Replication on KOSPI200 contradicts Bollen-Whaley daily result (see section 1).
- No Indian-market or Nifty-specific study of demand pressure or dealer gamma was found in any search.

### Inferences
- None of the headline findings was shown to hold using only EOD OI and volume. The one study that touches unsigned public measures (unsigned P/C ratio, 2014) is a single-stock study with an abstract-level claim only.

### Gaps
- No decay statistics (post-publication performance) were found for any of these effects; only the qualitative Terstegge sign flip and the vendor/independent backtests above.

---

## 7. Implications for a Nifty backtester

### Takeaway
With EOD strike-level settle, OI and volume (no bid/ask, no trade direction, no open/close tag), the signed order-flow measures of Bollen-Whaley, Pan-Poteshman, GPP and Chen-Joslin-Ni cannot be built. What can be built are crude public-OI proxies (OI-based gamma "exposure", OI concentration, OI change, volume/OI turnover, PCR) whose literature support is weak, and whose incremental value over India VIX / ATM IV is the key test. Treat all as exploratory hypotheses.

### Cited Findings (the evidence these inferences rest on is in sections 1-6; no new external sources)
- See sections 1-6 for sources. Data constraint confirmed by [Pan-Poteshman via later citing study](https://www.sciencedirect.com/science/article/abs/pii/S037842661400106X) (signed ratios need proprietary data) and by the vendor-side admission that dealer gamma is estimated, not observed ([FlashAlpha](https://flashalpha.com/articles/gex-dex-vex-chex-8-year-backtest-spy-vix-control)).

### Inferences

**What cannot be proxied from EOD OI/volume by strike**
- Signed net buying pressure (Bollen-Whaley), end-user vs dealer positions (GPP), buy-to-open put-call ratio (Pan-Poteshman), PNBO (Chen-Joslin-Ni): all need trade direction and open/close flags. OI change is net of opens and closes and has no side.
- Intraday timing results (Baltussen et al. last-30-minute momentum; Amaya et al. one-minute gamma): daily EOD data cannot test them. (Note the project's mid-session fill proxy `nifty_open + 0.40*(close - open)` is itself a modelling assumption, so intraday dynamics of the user's backtest are only approximate.)
- Real dealer sign on NSE: unknown. NSE index option customers vs proprietary/dealer composition is not in the archive and was not researched here (gap).

**Concrete testable features (all EOD, strike-level), with evidence strength and failure modes**
1. Strike-level OI-weighted gamma "exposure" (sum over strikes of gamma x OI x lot size x spot^2 under an assumed sign, e.g. customers net long puts / short calls as US GEX vendors assume), computed from Black-Scholes using India VIX or per-strike IV from settle prices. Test target: next-day and next-5-day realized vol, and weekly short-strangle/iron-condor P&L. Evidence strength: low for forecasting (vendor claims; one independent backtest says no incremental value over ATM IV; academic work with observed dealer positions finds small aggregate effect). Failure modes: dealer sign assumption wrong for NSE; collinearity with India VIX and DTE; weekly expiry-day OI concentration dominates.
2. Gamma-flip / zero-gamma strike distance relative to spot as a regime flag (positive gamma = range-bound, negative = trend). Evidence: conceptual support from Baltussen et al. and Barbon-Buraschi (sign-based, using different proxies); no Nifty evidence. Failure modes: flip level is highly sensitive to the sign assumption and to IV surface; requires the EOD settle-implied IV, which is noisy for illiquid strikes.
3. OI concentration / max-pain / pin-risk near expiry: share of OI at the nearest strikes to spot as a gamma-pinning flag on expiry week. Evidence: the stock-expiry strike-clustering result is from Ni, Pearson & Poteshman (JFE 2005, US stocks, title found only; contents not read) — [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0304405X05000577). No Nifty evidence. Failure modes: Tuesday cutover (2025-09-01) changes the calendar; expiry-day settle is not an option price in the archive (per project CLAUDE.md), so pin tests must use spot, not option marks.
4. Unsigned put-call ratios (OI-PCR, volume-PCR) and their changes as a skew/risk-premium state variable. Evidence: weak. One 2014 study claims unsigned P/C has predictive power (US, abstract-level); NSE broker PCR bands are untested; ambiguity between put buying and put writing. Failure modes: sign ambiguity, mean reversion within monthly expiry cycle, mechanical OI build-up as expiry approaches.
5. Volume/OI turnover by strike (unsigned activity) as a proxy for demand pressure on OTM puts. Evidence: no direct support; the theory (GPP) says demand matters through unhedgeable risk, which turnover does not measure. Use only as an exploratory control.
6. Skew from settle-implied IV across strikes (put wing vs ATM) as the *outcome* of demand pressure (GPP/Bollen-Whaley say wing richness reflects net demand). Evidence: theory + US index results; for premium selling the relevant claim is that expensive OTM puts earn a premium (GPP "index options expensive"). This is testable directly in the user's data via realised vs paid P&L by delta bucket. Failure modes: model-vs-real pricing mismatch noted in the project's CLAUDE.md (BS overstates weekly credit); settle prices not tradable quotes.

**Overall assessment**
- Strongest literature is for features the user cannot build (signed flow). Buildable features have the weakest evidence and the main failure mode is that they merely proxy for India VIX / ATM IV and DTE. Any test should include India VIX (and ATM IV) as controls and use pre-registered, out-of-sample or walk-forward evaluation, since the project's own chain-engine result is already "NOT SUPPORTED" for the baseline weekly strategy.

### Gaps
- Whether NSE publishes participant-wise (FII/DII/Pro/Client) OI or volume that could stand in for signed flow was not researched here; it falls outside the retrieved sources and may be covered by another researcher.
- No full-text verification of any paper; all table-level numbers are missing.
- Unreachable domains from WebFetch (DNS failure): www3.nd.edu, www.nber.org, papers.ssrn.com, pure.eur.nl, alphaarchitect.com, causalclaims.trfetzer.com, arxiv.org, dspace.kaist.ac.kr, www.mit.edu, econpapers.repec.org. WebSearch worked and returned URLs for the Notre Dame, NBER, SSRN, Cboe, Wiley and USC PDFs, which were not retrievable.
