# Cost-benefit of hedges for option writers and equity-index overlays: covered calls, collars, put protection, tail hedges

## 0. Source access and evidence quality (read first)

### Takeaway
No primary full text was read. WebFetch failed on every host tried with DNS errors (getaddrinfo ENOTFOUND), so everything below comes from WebSearch result summaries of the papers. Treat every number as "reported by a search summary of the paper" until checked against the PDF. The task title "Covered call strategies: one fundamental and two behavioral" did not match any paper; the closest are "Covered Calls Uncovered" (FAJ 2015) and "Covered Call Strategies: One Fact and Eight Myths" (FAJ 2014).

### Cited Findings
- Hosts that failed on WebFetch: www.aqr.com, aqr.com, rpc.cfainstitute.org, www.msci.com, ageconsearch.umn.edu, www.cxoadvisory.com, ueaeprints.uea.ac.uk, papers.ssrn.com, alphaarchitect.com, quantpedia.com. All returned `getaddrinfo ENOTFOUND`. Reachable only through WebSearch: aqr.com PDFs, SSRN, pm-research.com, researchgate, cambridgeassociates.com, risk.net, and others, as search-result summaries only.
- I tried to read the proxy README and status endpoint through Bash. The permission classifier denied that call, so I did not retry it or look for a workaround. Retrying with a working fetch path or reading the PDFs directly would close most gaps below.
- A search for the exact title "Covered call strategies: one fundamental and two behavioral" returned no such paper. Search returned "Covered Call Strategies: One Fact and Eight Myths" (FAJ, 2014) and "Covered Calls Uncovered" (FAJ 2015, Vol 71 No 6) — [IDEAS record](https://ideas.repec.org/a/taf/ufajxx/v71y2015i6p44-57.html), [SSRN 2444999](https://papers.ssrn.com/sol3/Papers.cfm?abstract_id=2444999), [T&F](https://www.tandfonline.com/doi/abs/10.2469/faj.v71.n6.1).

### Inferences
- The user's title is probably a conflation. The three-way decomposition (equity, short vol, equity timing/reversal) is in "Covered Calls Uncovered". The behavioral material (Shefrin-Statman, mental accounting) is from other literature.

### Gaps
- No primary-text verification of any figure below. No tables, footnotes or transaction-cost assumptions were read.

## 1. Covered calls: Israelov & Nielsen decomposition and follow-ups

### Takeaway
Covered-call return is mostly passive equity beta. The short-volatility leg is the only compensated option exposure (Sharpe near 1.0, about 10% of risk). A third "equity reversal/timing" exposure adds roughly 25% of risk with little return.

### Cited Findings
- "Covered Calls Uncovered", Israelov & Nielsen, Financial Analysts Journal 71(6), 2015. Only the abstract and secondary summaries were seen. It decomposes the strategy into three exposures: passive equity, short volatility, and equity reversal (timing). Equity drove most of the historical risk and return. Short volatility realized a Sharpe ratio of nearly 1.0 but contributed only about 10% of the risk. Equity reversal contributed about 25% of the risk and gave little return. The authors propose hedging the reversal exposure; the proposed strategy improved the Sharpe ratio and reduced volatility and downside equity beta — [AQR PDF](https://www.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/Covered-Calls-Uncovered.pdf) (search summary), [SSRN](https://papers.ssrn.com/sol3/Papers.cfm?abstract_id=2444999).
- The search summary did not confirm the sample period. I had guessed 1996-2014 in my query and that was not confirmed.
- "Covering the World: Global Evidence on Covered Calls", Israelov, Klein & Tummala, Journal of Risk. Applies the three-part attribution to covered calls on 11 global equity indexes. Equity drives most risk and return, short volatility has the best Sharpe ratio, and the equity-timing returns are statistically insignificant in all 11 indexes while contributing a relatively large share of risk. Data run through September 2015, common period from January 2006. A risk-managed variant hedges dynamic equity exposure with index futures. A third-party summary reports a 0.57 Sharpe for capitalization-weighted gross risk-managed covered calls, which is not verified against the paper — [AQR PDF](https://images.aqr.com/-/media/AQR/Documents/Journal-Articles/Covering-the-world-global-evidence-on-covered-calls.pdf), [SSRN 2990522](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2990522), [CXO summary](https://www.cxoadvisory.com/equity-options/covered-equity-index-calls-worldwide/).
- Behavioral side: Shefrin & Statman (1993) offer a prospect-theory/hedonic-framing explanation for the strategy's popularity; Siddiqi has a mental-accounting paper. Only abstract-level mention was seen — [search result via Investment Executive and others](https://www.investmentexecutive.com/news/industry/focus-on-products/beware-covered-calls/).

### Inferences
- For a short-premium book, the useful lesson is the "equity reversal" exposure. It is the part of a short-option book that loses on mean-reverting moves while earning nothing. This is an inference from the decomposition, not a quoted result. The paper's remedy (futures hedge of the dynamic delta) is a delta hedge, not a wing purchase.
- AQR's short-vol Sharpe near 1.0 is US/global-index, gross of the full cost of hedging. It is not evidence for Nifty.

### Gaps
- Exact sample, table values, transaction-cost treatment and robustness were not read. No Indian index is among the 11 that I could confirm.

## 2. Collars: Israelov & Klein (2016)

### Takeaway
The CBOE 95-110 collar earned much less than the index with a lower Sharpe. The shortfall comes from giving up equity risk premium and, where net long vol, paying the volatility risk premium. A 2025 AQR review reports the same cost for "cashless" collars.

### Cited Findings
- "Risk and Return of Equity Index Collar Strategies", Israelov & Klein, Journal of Alternative Investments, Summer 2016 (AQR working version June 2016). Only abstract and secondary summaries seen — [SSRN 2704518](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2704518), [AQR](https://www.aqr.com/Insights/Research/Journal-Article/Risk-and-Return-of-Equity-Index-Collar-Strategies).
- Strategy: the CBOE S&P 500 95-110 Collar Index (CLL) buys about 5% OTM three-month puts and sells about 10% OTM one-month calls (CXO Advisory summary) — [CXO](https://www.cxoadvisory.com/equity-options/equity-index-collar-performance/).
- Reported results (search summary; two sources disagree on sample start): Sharpe 0.47 for the S&P 500 versus 0.30 for CLL, about 35% lower. Excess return 3.2% per year for CLL versus 7.3% for the S&P 500; volatility 10.7% versus 15.7%. Sample July 1986 to December 2014 in one summary, while the CXO summary cites March 1996 onward for its comparison table — [ResearchGate listing](https://www.researchgate.net/publication/304610926_Risk_and_Return_of_Equity_Index_Collar_Strategies).
- Mechanism: collars are expected to earn less than the underlying primarily because they capture less equity risk premium. Collars that are net long vol give up additional return through the volatility risk premium — [AQR](https://www.aqr.com/Insights/Research/Journal-Article/Risk-and-Return-of-Equity-Index-Collar-Strategies). Benchmarks in the paper include cash-based deleveraging, puts alone and covered calls, and the collar was relatively weak among them (CXO and AQR supplement summaries).
- Practical Applications version exists — [pm-research](https://www.pm-research.com/content/iijpracapp/4/4/112).
- 2025 update: Asness, Cao, Ilmanen & Villalon, "Rebuffed: An Empirical Review of Buffer Funds", JPM 51(10), 2025. Analysing CLL and CLLZ (zero-cost) the net value of selling calls to fund puts is still negative in raw and risk-adjusted terms. The buffer-fund universe is the Morningstar Defined Outcome category from January 1, 2020 to April 30, 2025. Realized losses often exceed what payoff diagrams suggest. FT Vest disputed the findings as backward-looking and behavioral-benefit blind — [AQR PDF](https://www.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/JPM-Rebuffed-An-Empirical-Review-of-Buffer-Funds.pdf?sc_lang=en), [pm-research](https://www.pm-research.com/content/iijpormgmt/51/10/120), [AQR Buffer Madness](https://www.aqr.com/Insights/Perspectives/Buffer-Madness).
- A summary attributes the negative alpha to the put's volatility risk premium and skewness exposure (search summary of the 2025 paper).

### Inferences
- The put leg is the drag and the short call does not repay it. Per-leg Sharpe/return attributions are not in my extracts.
- Promotional/conflict flags: AQR sells alternative-risk-premia and trend products, and its hedging papers compare favorably to trend. FT Vest sells buffer ETFs and rebuts. Both are interested parties.

### Gaps
- Per-leg contribution table (put vs call legs) not recovered; extracted text was garbled in the search result. Sample dates are inconsistent across summaries.

## 3. Put protection: "Still Not Cheap" and "Pathetic Protection"

### Takeaway
AQR finds that the volatility risk premium (implied minus realized), not the level of implied vol, determines whether puts are cheap, and the VRP is positive most of the time, so protection is rarely cheap, even in calm markets. A later AQR paper finds protective puts weaker than simply de-risking for drawdown control unless timed.

### Cited Findings
- "Still Not Cheap: Portfolio Protection in Calm Markets", Israelov & Nielsen, Journal of Portfolio Management 41(4), 108-120, 2015 (issue season is shown as Spring in one record and Summer in another). Abstract-level only. Core claim: it is the VRP, the excess of implied over realized volatility, and not the absolute level of implied vol, that determines whether put protection is cheap or expensive — [SSRN 2579232](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2579232), [UEA digest](https://research-portal.uea.ac.uk/en/publications/still-not-cheap-portfolio-protection-in-calm-markets-digest-summa/).
- Secondary summary: from 1990 through 2014 the VRP averaged 3.4% and was positive 88% of the time. The paper extends to ten global equity indices and to black-swan replays including 1987 — [Alpha Architect summary](https://alphaarchitect.com/in-calm-markets-should-we-buy-cheap-put-protection/) (via search snippet; the page itself was not readable).
- A third-party site reports annual return 0.67% and Sharpe 0.20 over 1990-2026 for its replication; I could not verify and do not rely on it — [paperswithbacktest](https://paperswithbacktest.com/strategies/still-not-cheap-portfolio-protection-in-calm-markets).
- Per-VIX-regime results: not recovered. I did not see the regime table.
- "Pathetic Protection: The Elusive Benefits of Protective Puts", Israelov, Journal of Alternative Investments 21(3), Winter 2019, 6-33 (SSRN March 2017). Puts are "quite ineffective" at reducing drawdowns versus statically reducing exposure. Unless purchases and maturities are timed just right around drawdowns they may offer little protection and could increase drawdowns and volatility per unit of expected return. The divested portfolio nearly universally has better drawdown characteristics. Protected portfolio upside is higher (99th-percentile 250-day rally 36.7% versus 20.3% for divested). Nuance from the paper text: for large crashes, protective puts protect better than divesting; for modest daily crashes the divested portfolio does better. VRP embedded in puts negates much of the benefit — [SSRN 2934538](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2934538), [pm-research](https://www.pm-research.com/content/iijaltinv/21/3/6), [AQR PDF](https://images.aqr.com/-/media/AQR/Documents/Journal-Articles/Pathetic-Protection-JAI-Wint19.pdf), [Advisor Perspectives](https://www.advisorperspectives.com/articles/2019/08/22/are-puts-efficient-at-protecting-downside-risk.pdf).
- AQR later commentary says portfolio insurance is expensive on average and calm markets do not make a compelling case — [AQR Chasing Your Own Tail (Risk) Revisited](https://www.aqr.com/-/media/AQR/Documents/Insights/White-Papers/AQR-Chasing-Your-Own-Tail-Risk-Revisited.pdf?sc_lang=en).

### Inferences
- The VRP-not-level result is the most transferable point: a hedge-timing rule must use implied minus expected-realized, not raw VIX. India VIX (a level) would not be sufficient on its own.

### Gaps
- Per-VIX-regime numbers, the 10-index results (including whether any is non-US), transaction costs and robustness checks were not read. The 3.4%/88% figures are from a secondary summary.

## 4. Tail-hedge cost vs payoff: AQR, Cambridge Associates, MSCI, Universa and critics

### Takeaway
The independent practitioner studies found (AQR, Cambridge Associates, MSCI) lean toward tail hedges costing more than they pay on average, with CalPERS exiting for cost. The pro-hedge case comes from Universa and aligned commentary, which are promotional/interested, and argues for small, far-OTM, convex allocations that enable more risk-taking. The dispute is mostly about strike choice and how the hedge is funded.

### Cited Findings
- AQR "Chasing Your Own Tail (Risk)" (2011) argued the long-run cost of insurance-style tail hedges, whether direct put purchase or implicit collar cost, exceeds payouts. The 2019 "Revisited" tests puts using the CBOE PPUT index (long S&P 500 plus monthly 5% OTM puts) — [2019 PDF](https://www.aqr.com/-/media/AQR/Documents/Insights/White-Papers/AQR-Chasing-Your-Own-Tail-Risk-Revisited.pdf?sc_lang=en), [2011 PDF](https://www.aqr.com/-/media/AQR/Documents/Insights/White-Papers/AQR-Chasing-Your-Own-Tail-Risk.pdf).
- AQR "Tail Risk Hedging: Contrasting Put and Trend Strategies" (also Journal of Systematic Investing, Feb 2021). Compares a 5% OTM one-month S&P 500 put strategy with multi-asset trend. A table reports long-run put return about -6.4% versus about 8.7% for trend, before relatively high trading costs and fees (the extraction was garbled, so approximate). AQR concludes the cost advantage favors trend, while granting that "puts cost more but hedge better" has a kernel of truth — [AQR PDF](https://images.aqr.com/-/media/AQR/Documents/Insights/White-Papers/AQR-Tail-Risk-Hedging-Contrasting-Put-and-Trend-Strategies.pdf), [JoSI](https://www.aqr.com/-/media/AQR/Documents/Journal-Articles/Journal-of-Systematic-Investing-Vol-1-Issue-1--Tail-Risk-Hedging-AQR.pdf?sc_lang=en).
- Cambridge Associates, "Portfolio Protection: Challenges with Equity Put Options": for many investors the protection costs more than it delivers; behavioral pitfalls include mistimed purchases and early termination; recommends asset allocation first. Quantitative content not read — [Cambridge Associates](https://www.cambridgeassociates.com/insight/portfolio-protection-challenges-with-equity-put-options/).
- MSCI blog "Did hedging tail risk pay off?" (2020): tail-hedging costs have typically been high and likely outweigh benefits; simulated tail hedges lagged portfolios that simply reduced risky exposure unless very well timed before crises; implied probability of a drop and put price rise together — [MSCI](https://www.msci.com/research-and-insights/blog-post/did-hedging-tail-risk-pay-off). Authors and numbers not read.
- Newfound Research (2020) argues many studies hold options to expiration and that rolling puts before expiry lets investors profit from damage — [Newfound](https://blog.thinknewfound.com/2020/06/tail-hedging/). Rebuttal in kind; not verified.
- Universa/Spitznagel (promotional, sells the product): a deeply OTM put costs little and can rise many multiples; hedging lets an investor hold more risk assets; about 1% of the portfolio is suggested for the protocol. A 4,144% Q1-2020 return was reported from a leaked letter, but one report says it is a return on "required invested capital" and Forbes estimates actual capital at risk at 2-3% of the assets reportedly managed. CalPERS ended its Universa program in 2019 and its CIO said the managers were too costly — [Institutional Investor](https://www.institutionalinvestor.com/article/2bsx81qp5g2t3adglle68/portfolio/nassim-taleb-and-universa-versus-the-world), [FA Magazine](https://www.fa-mag.com/news/why-one-firm-s-3-612--return-is-drawing-the-ire-of-hedge-funds-72668.html), [Yahoo Finance](https://finance.yahoo.com/news/mark-spitznagel-univesa-cio-on-risk-mitigation-204157461.html), [Institutional Investor on CalPERS](https://www.institutionalinvestor.com/article/b1lf9zw3n8w3gt/Was-CalPERS-Right-to-Unwind-Its-Tail-Risk-Program).
- Critique of AQR: it used near-ATM-ish 5% OTM puts and funded them by selling the index, not a small deep-OTM overlay — blog commentary, not peer-reviewed — [Leptokurtic](https://federicocarrone.com/series/leptokurtic/the-tail-hedge-debate-spitznagel-is-right/).
- Scale limit: a very large fund faces too few far-OTM puts to buy (pomegra wiki, weak source, unverified).
- Cost estimates from blogs and lecture pages (unverified, conflicting): 4-6% per year for a 15% OTM put rollover; put spreads 1-3%; a CBOE Eurekahedge Tail Risk Hedge Fund Index drag of about 2.65% per year in normal markets — [search summary of Cambridge-related results](https://harbourfrontquant.substack.com/p/tail-risk-hedging-with-deep-out-of). Another source gives 0.2-0.8% for deep OTM and 1-3% for ATM protection. Do not use these numbers.
- A 2026 arXiv paper says puts are strongest against sudden crashes but rolling carries a persistent premium drag because implied variance exceeds subsequent realized variance; a 2026 thesis finds DOOM puts only help when strike region matches regime — [arXiv](https://arxiv.org/html/2607.00883v1). I did not read these; the arXiv ID looks odd for the date, treat as unverified.

### Inferences
- Even the best-argued pro-hedge case (Universa) rests on small allocations to far-OTM puts and on enabling more risk elsewhere, which is a portfolio-level argument. It does not show that a hedge adds return to a book that is already short vol.
- Research Affiliates' own tail-hedge work was not found by search; none is cited here.

### Gaps
- No primary text for Cambridge, MSCI or Newfound. Research Affiliates and Bhansali (PIMCO) work not found. No academic paper on static vs dynamic tail hedging found; the "dynamic vs static" debate is only represented by Newfound and the blog critique. No India/Nifty tail-hedge studies found.

## 5. Hedge cost vs VIX/IV level, skew richness and tenor; does timing help?

### Takeaway
Evidence is thin and mostly non-academic. The primary-source point is AQR's: cost follows the VRP, not the IV level. Timing evidence is inconclusive: Israelov (2019) says timing must be very precise to work; I found no study showing an IV-RV spread signal improves hedge purchases.

### Cited Findings
- VRP, not IV level, drives cost (Israelov & Nielsen 2015, above). VRP averaged 3.4% and was positive 88% of the time in 1990-2014 (secondary summary).
- Israelov (2019): unless purchases and maturities are timed just right, puts may add drawdown and volatility per unit of expected return.
- MSCI: the price of put insurance rises with implied probability of a drop, so protection is most expensive when it seems most needed.
- Skew (blog/vendor-level, unverified): 10% OTM put at 22.5% IV versus 12.5% for an equally distant call; one model attributes 0.2497 of a 0.5695 premium (44%) to skew for a 3-month 90 put; another says OTM puts trade 4-8 vol points above ATM and skew steepens in drawdowns; a 90/80 put spread costs 1.43 versus 1.78 for the outright 90 put in a model; some pages say IV exceeds RV by 2-4 vol points — [riskhub](https://riskhub.org/blogs/volatility-skew-and-crash-protection), [flashalpha](https://flashalpha.com/articles/risk-reversal-put-spread-collar-equity-hedging-compared), [findices](https://findices.com/articles/financial-hedging-strategies-what-the/). Vendor/education sources with conflicting cost ranges.
- Tenor: AQR benchmarks use one-month (PPUT, put strategy) and three-month (CLL) puts. I found no controlled tenor comparison.

### Inferences
- Cost-per-protection is likely higher at short tenors and for near strikes, but that is not established by what I read.

### Gaps
- No evidence found on cost by VIX regime (the per-regime table in "Still Not Cheap" was not read), tenor, or on IV-RV-spread-timed purchases. Nothing on emerging-market indices.

## 6. Replication, decay, sample dependence, conflicts and bias flags

### Takeaway
The negative-expected-return finding for index puts and collars has been restated by the same group (AQR) across 2011, 2015, 2016, 2019, 2021 and 2025, so it is consistent but not independent. The countervailing evidence is mostly from sellers of tail hedges.

### Cited Findings
- AQR repeated the cost message in 2025 on a new sample (buffer funds, 2020-April 2025, plus the CLL/CLLZ indices) — [AQR](https://www.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/JPM-Rebuffed-An-Empirical-Review-of-Buffer-Funds.pdf?sc_lang=en). The 2025 review is said to extend the collar index history to May 2025 and finds the long-term cost persists (search summary).
- Sample dependence: sample ends vary (2014 for the collar paper, 2015 for global covered calls). 2020 crash results are the standard counterexample used by Universa; CalPERS exited before that crash, per Institutional Investor.
- Conflicts: AQR (puts cost more than they pay; trend better) versus Universa/Spitznagel and Newfound (small convex allocation or rolled puts help). Disagreement is about strike (5% OTM versus deep OTM) and funding (selling index) and horizon, not about whether average premium is positive.
- Bias flags: AQR (sells trend and risk-premia products), Universa (sells tail hedges), FT Vest (sells buffer ETFs), Alpha Architect, CXO and paperswithbacktest (secondary aggregators; some sell products). Blogs and vendor educational pages are low reliability.
- Everything here is US/global developed indices. No replication on Nifty or any emerging market.

### Inferences
- Treating the AQR series as five confirmations overstates the independent evidence; it is one research group using similar CBOE indices.

### Gaps
- No independent academic replication or out-of-sample test found; no decay study found.

## 7. Implications for hedging a Nifty short-premium book

### Takeaway
The literature supports treating hedges as risk-limiting costs, not return enhancers. The testable ideas below are inferences from the cited work, not results from it. All need to be tested on real NSE chain data, noting the repo's own caveats (BS pricing overstates credit; real-price chain engine uses EOD settle marks, no bid/ask).

### Cited Findings
- Cost of puts and collars is persistently positive on US data: [Israelov & Klein](https://www.aqr.com/Insights/Research/Journal-Article/Risk-and-Return-of-Equity-Index-Collar-Strategies), [Israelov](https://www.pm-research.com/content/iijaltinv/21/3/6), [AQR 2019](https://www.aqr.com/-/media/AQR/Documents/Insights/White-Papers/AQR-Chasing-Your-Own-Tail-Risk-Revisited.pdf?sc_lang=en).
- VRP, not IV level, sets hedge cost: [Israelov & Nielsen 2015](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2579232).
- Static de-risking beat protective puts on drawdown in most windows, but puts protected better in large crashes: [Israelov 2019](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2934538).
- The short-vol leg of a covered call earned a high Sharpe; the equity-reversal exposure added risk without return: [Covered Calls Uncovered](https://papers.ssrn.com/sol3/Papers.cfm?abstract_id=2444999).

### Inferences
Concrete testable rules (all hypotheses):
1. Defined-risk wings as the default. Compare an iron condor or put credit spread (short strike plus wing) to a naked short strike at the same short delta. Test wing distances (for example 2%, 4%, 6% beyond the short strike) and a cost cap: skip the wing if its price exceeds a fixed share of the credit (for example 20-30%), then report net expectancy per lot, max loss and drawdown. Wings are a hard-stop substitute for the repo's 2x credit stop, which the chain engine cannot test intraday.
2. Static far-OTM put overlay on the book. Fixed small budget (for example 0.5-1% of capital per year, from Spitznagel's ~1% figure, which is a promotional source), monthly roll, 8-12% OTM. Judge it on drawdown reduction per unit of return given up, against the simple alternative of cutting lot count (Israelov 2019 benchmark).
3. Collar-style structure. Fund the long wing with a short call or call spread on the weekly track. Expect negative carry from literature (CLL/CLLZ); test only as risk control, and note a short-premium book already carries short upside exposure, so a short call adds exposure rather than hedges it. Put-spread collars are untested here.
4. Conditional purchase. Buy wings or a put overlay only when implied minus expected-realized vol (India VIX versus trailing realized Nifty vol) is small or negative, or when drawdown/crash score gates in the repo trip. Israelov & Nielsen support using the spread rather than the VIX level; no study shows this improves outcomes, so test it against always-on.
5. Delta/reversal management. Because "equity reversal" exposure is uncompensated in covered calls, test whether delta-hedging the net book with Nifty futures cuts risk without cutting return.
6. Compare each hedge to the de-risking baseline (fewer lots, or the repo's existing VIX gate and DD kill switch) on the same capital.

Caveats for Nifty:
- India VIX has no listed options or tradable futures that I confirmed in these sources, so a vol-based tail hedge (long VIX calls) is unavailable here; this is not covered by the literature I read and should be verified.
- Far-OTM Nifty option liquidity, bid/ask and EOD-settle marking are major model risk. The repo's chain engine has no bid/ask, so hedge cost would be understated.
- Everything cited is US or developed-market. Skew, VRP size and retail flow differ in India; do not import AQR's 3.4% VRP or Sharpe figures.
- Weekly Nifty expiries and the Tuesday cutover mean tenor choices differ from the one- and three-month structures in the literature.

### Gaps
- No India-specific hedge, skew or VRP evidence was retrieved. No source tested wing distance rules directly.
