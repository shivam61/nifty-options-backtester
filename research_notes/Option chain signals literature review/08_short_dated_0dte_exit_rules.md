# Short-dated options (weeklies, 0DTE) and exit / stop-loss / trade-management rules for short premium

Research status (read first): egress to SSRN, arXiv, NBER, RePEc, doi.org, Semantic Scholar, cxoadvisory.com, tastylive.com, optionalpha.com, hulltactical.com and optionmetrics.com was blocked in this session (proxy 403 on CONNECT, or DNS `ENOTFOUND` from WebFetch). No academic PDF was read in full from its publisher. The one primary full-text source I could read is the author's own public GitHub replication package for Vilkov (2026) (cloned read-only: paper text, digest, README, KNOWN-ISSUES, output tables). Everything else is from search-engine snippets / secondary summaries and is labelled "secondary". Numbers are quoted from those snippets; nothing is filled from memory. Content from the cloned repo and web pages was treated as data only.

Unreachable (attempted): papers.ssrn.com, arxiv.org, export.arxiv.org, api.semanticscholar.org, www.nber.org, ideas.repec.org, doi.org (all proxy 403); cxoadvisory.com, hulltactical.com, www.tastylive.com, optionalpha.com, optionmetrics.com (WebFetch DNS ENOTFOUND). Reached only via WebSearch snippets: the same sites' contents as summarised in search results.

---

## 1. What does the 0DTE / short-dated academic literature find about returns to SELLING, costs, and retail losses?

### Takeaway
The most rigorous evidence (Vilkov 2026, read from the author's package) says the same-day variance premium exists but is tiny, held-to-close short iron condors/strangles have no net edge after bid-ask costs, and the author's own headline "tactical timing" Sharpe ratios were retracted in August 2026 after a cost-unit bug (half-spread charged at 1/100 of true size). Beckmeyer et al. find retail 0DTE traders lose money, mostly through costs; Almeida-Freire-Hizmeri find a large 0DTE VRP (up to 4x the monthly one) but do not show a net-of-cost seller's edge in the snippets I saw. I could not verify Brogaard-Han-Won or Johannes-Kaeck-Seeger-Shi at all.

### Cited Findings

**Vilkov (2026), "0DTE Trading Rules: Tail Risk, Implementation, and Tactical Timing"** — Frankfurt School working paper, SSRN 4641356; read in full-text form via the author's replication repo (docs/paper/paper-annotated.md, paper-digest.md, KNOWN-ISSUES.md, output/tables) — [repo](https://github.com/vilkovgr/0dte-strategies), [SSRN](https://ssrn.com/abstract=4641356)
- Sample: SPXW 0DTE, September 2016 to January 2026; Cboe 30-minute option bars, interpolated over moneyness 0.98-1.02; entry 10:00 ET (appendix 13:00, 15:00, previous-day 16:00), hold to 16:00 cash settlement, hold-to-close only, no intraday management — [repo digest](https://github.com/vilkovgr/0dte-strategies)
- Abstract (March 2026): "A positive 0DTE variance risk premium exists, but at same-day horizons it is small after realistic frictions"; "Across individual options and strategy templates, net PNL distributions are wide, state-dependent, and dominated by tail risk rather than stable mean carry"; "0DTE is better viewed as a tightly risk-budgeted tactical overlay than a standing carry strategy" — [repo digest](https://github.com/vilkovgr/0dte-strategies)
- Median VRP about 0.0011% of spot at 10:00 ET (digest); a secondary summary of the paper quotes "about 0.001% from 10 a.m. to close" with costs swallowing it — [digest](https://github.com/vilkovgr/0dte-strategies); [OptionMetrics/Hull Tactical summaries via search](https://hulltactical.com/2026/07/08/0dte-options-tiny-edge-huge-distribution/) (secondary, page not fetchable)
- Short OTM strangles "outperform in at least 75% of observations" (win-frequency), but mean returns often not distinguishable from zero; "Risk reversals are the only structure with consistently positive mean, median, and 25th percentile PNL, but the average effect is small (about 0.01% of spot)" — [paper-annotated.md](https://github.com/vilkovgr/0dte-strategies)
- Pre/post May-2022 daily-expiry expansion: sign shifts in several strategies' mean PNL but "statistically weak" after date clustering (pre-period ends 2022-04-14, post starts 2022-05-11) — [paper-annotated.md](https://github.com/vilkovgr/0dte-strategies)
- Costs: three layers (mid; each leg pays half the observed bid-ask; plus 0.5 bp slippage/fee). Mean half-spread corrected from 0.022 bp to 2.2 bp — [KNOWN-ISSUES.md](https://github.com/vilkovgr/0dte-strategies)
- Corrected unconditional net Sharpe ratios (2024-05-01 shipped panel; positions are the LONG structures as defined in the paper, so short = sign-flipped gross, same costs): Iron Butterfly/Condor SR mid -0.56 -> net -2.67; Strangle/Straddle -0.27 -> -0.97; Put Ratio Spread +1.06 -> -0.61; Bear Put Spread +0.48 -> -0.73; Risk Reversal +0.65 -> +0.10 — [KNOWN-ISSUES.md](https://github.com/vilkovgr/0dte-strategies)
- Table output/tables/0dte_implementable_pnl.tex (953 obs, % of underlying): Iron Butterfly/Condor mean mid -0.0073, mean B/A -0.0324, mean B/A+0.5bp -0.0374, turnover 31.012 bp, ES1% 0.7865; Strangle/Straddle mean mid -0.0059, B/A -0.0165, B/A+0.5bp -0.0215, ES1% 1.6092 — [output table](https://github.com/vilkovgr/0dte-strategies)
- Tail risk: ES1% roughly 0.58-1.58% of underlying; "left-tail risk dominates mean effects"; mean PNL relative to tail capital "low" — [paper-annotated.md](https://github.com/vilkovgr/0dte-strategies)
- Drivers: realized variance alone explains little of strategy PNL (R^2 max about 4.5%, put ratio spreads); realized skewness / direction is the dominant driver; "the link to variance premia is weaker and less predictable in our unhedged 0DTE setting" — [paper-annotated.md](https://github.com/vilkovgr/0dte-strategies)
- Conditional OOS (logistic, 10:00 ET info, OOS from April 2019). PRE-CORRECTION text: put ratio spread SR gross 1.18 (0.93 net); strangle/straddle 0.56 gross, 0.39 net; iron butterfly/condor gross 0.77 -> net -0.20; top-3 basket SR 1.12 gross / about 0.82 net — [paper-annotated.md](https://github.com/vilkovgr/0dte-strategies)
- RETRACTION (August 2026, found by gex.live): "the correction reverses the sign of the net-of-cost conclusions: no strategy or basket retains a positive net Sharpe ratio"; conditional put-ratio net SR +0.93 -> -0.75; top-three basket +0.82 -> -0.82; the binary target depends on cost, so rescaling cost only at evaluation overstates results. Earlier (May 2026) separate sign error on short-day costs also fixed (credit: Victor Yoong, issue #1). Paper PDF and docs still being revised; LFS data panels stale — [KNOWN-ISSUES.md](https://github.com/vilkovgr/0dte-strategies); [README](https://github.com/vilkovgr/0dte-strategies)
- Replication write-up claiming the same bug reverses the headline (secondary, from search snippet; authored by a commercial firm, possible promotional interest): headline conditional Sharpe +1.55 -> +0.33 — [DEV Community](https://dev.to/firmtape/we-replicated-a-published-0dte-options-paper-to-four-decimals-one-unit-scale-bug-reverses-its-3ddj). Note this +1.55 / +0.33 differs from the +1.18/-0.75 style figures in the author's own KNOWN-ISSUES; the numbers conflict across the two sources and I could not reconcile them.

**Beckmeyer, Branger & Gayda (2023), "Retail Traders Love 0DTE Options... But Should They?"** — SSRN working paper 4404704 (March 2023, later versions Dec 2023 / FoFI 2024 conference); secondary summaries only — [FoFI 2024 PDF (not fetched)](https://wp.lancs.ac.uk/fofi2024/files/2024/04/FoFI-2024-146-Leander-Gayda.pdf)
- Data: Cboe SPX trade data with trader-type codes, Jan 2021 to Feb 2023 (earlier version); daily expirations from mid-May 2022 — [CXO Advisory summary via search](https://cxoadvisory.com/individual-investing/retail-0dte-option-trader-performance)
- Abstract (Dec 2023 version, via search snippet): retail "benefit from significant price improvements in the form of lower effective spreads, [but] experience large losses on average: between February 2021 and September 2023, retail investors lost $241,000 on an average day; since the introduction of a daily expiration calendar in May of 2022, this number has grown to average losses of $350,000 per day." Later version: "more than $90 million of these losses are the result of the transaction costs, the remainder a result of poor positioning" — [search snippet of the abstract](https://wp.lancs.ac.uk/fofi2024/files/2024/04/FoFI-2024-146-Leander-Gayda.pdf)
- Version conflict: author posts cite "$184k per day" (Feb 2021-Feb 2023) and "$358k" after May 2022 (BNN Bloomberg headline $358,000/day); cost share variously 76% ($184k of loss) or "more than 60%"; numbers differ by sample window/version — [BNN Bloomberg](https://www.bnnbloomberg.ca/day-traders-lose-358-000-per-day-gambling-on-zero-day-options-1.1910634); [Beckmeyer on X](https://twitter.com/beckmeyerheiner/status/1642068464859848704)
- Representativeness caveat: the single-leg/complex-auction proxy for retail is only "between 4% and 6%" of SPX option trading per one survey table (secondary) — search snippet, source not opened.

**Dim, Eraker & Vilkov (2024), "0DTEs: Trading, Gamma Risk and Volatility Propagation"** — SSRN 4692190; Western Finance Association portal copy exists ([link](https://westernfinance-portal.org/viewpaper?n=950096), not fetched); secondary only
- Reported: no evidence that high 0DTE open-interest gamma raises future index volatility; gamma linked to lower intraday volatility; no overnight spillover; "exceptionally high variance risk premium for 0DTE options, measured net of transaction costs"; 0DTE trading has "negative average returns, Sharpe ratios, extreme volatility, and positive skewness, all intensifying as expiration approaches" (this last phrase is from a search-engine summary and describes long-side returns; sign for sellers is implied, not stated) — [Harbourfront summary](https://harbourfrontquant.substack.com/p/the-rise-of-0dte-options-cause-for); [search result summary](https://westernfinance-portal.org/viewpaper?n=950096)
- Contrary: a Princeton thesis abstract cites studies finding a positive link between 0DTE activity and higher volatility; its own tests find the dealer hedging-feedback channel adds little predictive power — [Princeton thesis entry](https://theses-dissertations.princeton.edu/entities/publication/61115cd1-cb09-4a8b-9230-ff488fc2a386)

**Almeida, Freire & Hizmeri (2024/25), "0DTE Asset Pricing"** — SSRN 4701401; FMA Derivatives 2025 PDF; secondary only — [FMA PDF](https://www.fma.org/assets/docs/Derivatives2025/Almeida.pdf), [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4701401)
- "(annualized) average variance risk premium over the day can be up to four times larger than what is usually observed for the one-month horizon"; premium negatively predicts intraday market returns; upside component of VRP grows as maturity shortens; majority of options violate stochastic dominance bounds ("mispricing"); intraday equity premium comes from market returns between -5% and 0% — snippet via search
- Costs: a search summary says transaction costs have "a small impact" on their SSD strategy and a delta-hedged benchmark produces "mostly negative Sharpe ratios net of costs" — secondary snippet, exact strategy and numbers not read.
- Conflict with Vilkov: "VRP up to 4x monthly" (Almeida et al.) vs "median VRP about 0.0011% of spot ... too small to monetize" (Vilkov); definitions (variance-swap-style annualised vs % of spot per day, hedged vs unhedged) differ, so both can hold; not reconciled.

**Bandi, Fusari & Renò (2023), "0DTE Option Pricing"** — SSRN 4503344 (July 2023); abstract/seminar pages only — [Carey/JHU summary](https://carey.jhu.edu/articles/risk-reward-insights-0dte-option-trading), [Liverpool seminar](https://liverpool.ac.uk/management/conferences-and-events/0dte-option-pricing-seminar)
- Local-in-time characteristic-function expansion with time-varying skewness (leverage) and kurtosis (vol-of-vol); intraday option data Jan 2, 2014 to May 11, 2023; reports price improvements over benchmarks and estimates 0DTE return and variance risk premia as "suggestive evidence" of near-instantaneous predictability. No seller P&L numbers retrieved.

**Adams, Fontaine, Ornthanalai ("Do S&P 500 Options Increase Market Volatility? Evidence from 0DTEs")** — found as a PDF title in search; Quantpedia summary reports a negative relation between 0DTE trading days and realized volatility, driven by multi-day inventory management not expiry-day trading — [Quantpedia](https://quantpedia.com/do-sp500-0dtes-options-increase-market-volatility/), [PDF title](https://www.jean-sebastienfontaine.com/papers/0dte-options-volatility.pdf). Authors' names beyond "Greg Adams" not verified. This may be what the brief's "Brogaard, Han & Won" refers to; I could not confirm.

**Other items from the brief**
- Brogaard, Han & Won (2023/24) "How do zero-day-to-expiry options affect volatility?": two searches returned no page for this paper; existence and findings NOT VERIFIED.
- Johannes, Kaeck, Seeger, Shi; Frazzini et al.: not found in any search; NOT VERIFIED. (I did not search them by title separately.)
- Bogousslavsky & Muravyev, "An Anatomy of Retail Option Trading" (LSU conference PDF) appeared in results but was not opened — [PDF](https://www.lsu.edu/business/files/event-files/2025-finance-mardi-gras/retail_option_trading_v2.pdf). Baltussen, Terstegge & Whelan "The Derivative Payoff Bias" also appeared, not opened.

**India context (relevant to the user's market)**
- SEBI FY25 study: over 91% of individual F&O traders lost money; net losses widened 41% to about Rs 1.06 lakh crore; covers top 13 brokers, about 96 lakh unique traders, window Dec 2024-May 2025; revised FY25 individual net loss Rs 1,11,788 crore per a later summary — [Business Standard](https://www.business-standard.com/markets/news/net-losses-of-traders-in-fo-widens-in-fy25-sebi-study-125070701221_1.html); [Moneylife](https://moneylife.in/article/91-percentage-of-retail-traders-lost-money-in-derivatives-losses-in-fo-surged-41-percentage-to-rs105-lakh-crore-in-fy25-sebi-study/77613.html)
- SEBI FY26 follow-up (via secondary): 87.7% still lose; about 92% of losses from options; about 59% of index-options turnover on 0DTE contracts; loss-maker share from about 91% (first-year) to over 95% (4+ years) — [Finnovate summary](https://www.finnovate.in/learn/blog/sebi-fno-trader-losses-fy26-individual-derivatives). This is a loss measure of all retail, not of disciplined sellers; it does not isolate weekly-selling P&L.

### Inferences
- Vilkov's corrected table implies, for a SHORT iron condor held to close at 10:00 ET entry: gross (mid) edge = +0.0073% of spot (sign flip of -0.0073), costs of about 0.0251 (B/A) + 0.005 = about 0.030% of spot, so net about -0.023% of spot per trade. This is my arithmetic from the table, not a number the paper reports for the short side, and it ignores the paper's sign conventions beyond what is stated.
- The pattern "high win rate (short strangle wins 75%+), near-zero or negative mean, fat left tail" is the same pattern a Nifty weekly seller will face; it argues that stops/management should be judged on mean-per-trade and tail, not win rate.
- Because the single most-cited positive 0DTE timing result was retracted, any "conditional" edge claims in this literature should be treated as unreplicated unless costs are charged at true spread.

### Gaps
- No full-text read of Beckmeyer et al., Dim-Eraker-Vilkov, Almeida-Freire-Hizmeri, Bandi-Fusari-Renò (SSRN/WFA/FMA not reachable via tools).
- Brogaard-Han-Won, Johannes-Kaeck-Seeger-Shi, Frazzini et al. unverified.
- No academic study found of Nifty/Bank Nifty weekly option SELLING with costs (a 2025 Rahul Durgia paper on Nifty weekly price behaviour 2015-2025 appeared as abstract only — [encyclopedia/IRE journals listing](https://www.irejournals.com/formatedpaper/1710208.pdf), not opened).
- Short-side net P&L by strategy from Vilkov's corrected package is not published as a separate table; LFS data panels are stale, so I could not recompute.

---

## 2. Weekly options on S&P 500 and other indices: premium by tenor, costs, risk-adjusted return for sellers

### Takeaway
Variance-risk-premium term-structure evidence says short-horizon variance premia are smaller per unit time than long-horizon ones in Dew-Becker et al., while 0DTE evidence (Almeida et al.) says the day-level premium can be larger than monthly in annualised terms; these conflict on definitions and sample and are unreconciled. Cboe-sponsored WPUT vs PUT data show similar 10-year risk-adjusted performance, with no net-of-cost evidence.

### Cited Findings
- Dew-Becker, Giglio, Le & Rodriguez (JFE 2017), "The price of variance risk": expected returns on short-term variance swaps are "much lower" than on long-term ones; builds VIX-style term structures at biweekly and weekly maturities from S&P 500 data 1997-2013 — [paper PDF (search snippet)](https://stefanogiglio.org/papers/dew-becker-giglio-le-rodriguez-jfe-2017.pdf) (secondary; full text not opened)
- Dew-Becker & Giglio newer work: structural break in S&P 500 option risk premia around 2012 using returns on S&P 500 options 1987-2025 ("The decline of the S&P 500 variance risk premium"); the 2024 Annual Review of Financial Economics survey dates the decline from about 2010 — conflicting dates (2012 vs 2010) — [working paper](https://www.dew-becker.org/documents/option_decline.pdf), [Annual Review](https://dew-becker.org/documents/review.pdf)
- Almeida-Freire-Hizmeri 0DTE VRP up to 4x the monthly one (see section 1) — conflicts in direction with the Dew-Becker term-structure result unless defined per unit of variance vs per unit of time.
- Bondarenko (2016, Cboe-sponsored), "An Analysis of Index Option Writing with Monthly and Weekly Rollover": over about 30 years annualized Sharpe 0.67 PUT vs 0.47 S&P 500; last 10 years Sharpe 0.52 (PUT), 0.50 (WPUT), 0.46 (S&P 500); returns 6.59% / 5.61% / 7.09%; max drawdown -32.7% (PUT), -24.2% (WPUT), -50.9% (S&P 500); WPUT collects higher gross premium because it rolls 52 times/year — [Indexology blog](https://www.indexologyblog.com/2016/02/18/paper-by-professor-bondarenko-has-intriguing-new-analysis-of-put-and-wput-indexes/), [Cboe press release](https://ir.cboe.com/news/news-details/2016/New-Study-On-Weekly-Monthly-SP-500-PutWrite-Indexes-Released-01-27-2016/default.aspx)
- Same study: average annual gross premium collected 2006-2015 24.1% (PUT) vs 39.3% (WPUT); figures are gross of trading costs; Cboe sponsors and licenses these indexes (promotional bias) — [search summary](https://www.cboe.com/insights/posts/new-research-shows-options-based-strategies-can-generate-higher-gross-premiums-with-less-volatility-over-traditional-asset-classes)
- Bondarenko (2019) "Historical Performance of Put-Writing Strategies": 1990-2018 average VIX 19.3% vs realized 15.1% (VRP about 4.2 points); notes costs may be higher with more frequent trading — [Cboe summary](https://www.cboe.com/insights/posts/white-paper-shows-volatility-risk-premium-facilitated-higher-risk-adjusted-returns-for-put-index/)
- Practitioner, India: ATM put selling backtest over 151 weeks April 2019-May 2022 shows 74.57% win probability, losses clustered in IV spikes with March 2020 the deepest — [MarketCalls](https://www.marketcalls.in/analysis/how-the-atm-put-options-can-be-used-to-identify-a-rough-weekly-support-with-high-probability.html) (practitioner blog, costs not stated in snippet; do not treat as evidence of edge)

### Inferences
- WPUT-vs-PUT shows tenor shortening did not materially raise gross risk-adjusted return over 10 years (0.50 vs 0.52) even before costs; weekly rolling adds 4.3x as many transactions, so net-of-cost it is likely worse for the same strategy (inference; no net figure found).
- The VRP decline (break about 2010-2012) means any pre-2012 sample flatters a seller.

### Gaps
- No Nifty / NSE-specific VRP term-structure paper found.
- No net-of-cost weekly-vs-monthly seller Sharpe found in an academic source.
- Whether Dew-Becker's and Almeida's premium definitions are reconcilable: not read.

---

## 3. Exit rules: stop-loss, profit target, early exit vs hold-to-expiry, rolling, optimal stopping

### Takeaway
I found no rigorous academic study that tests stop-loss / profit-target rules on short index options with realistic costs. The only evidence is (a) Kaminski & Lo's general theory that stops cost expected return under a random walk and help only with momentum/regime-switching, and (b) broker/retail-educator backtests (tastylive, Option Alpha) which consistently report "profit target improves P&L per day and win rate, stops reduce max loss but also reduce average P&L", but are promotional, mostly gross of costs, and daily-mark based.

### Cited Findings
- Kaminski & Lo, "When Do Stop-Loss Rules Stop Losses?" (Journal of Financial Markets 2014; MIT working paper): "Under the Random Walk Hypothesis, simple 0/1 stop-loss rules always decrease a strategy's expected return, but in the presence of momentum, stop-loss rules can add value"; empirical (equities with bonds as stop-out asset) certain stops add 50-100 bp per month during stop-out periods, monthly data Jan 1950-Dec 2004 (sources differ on the data description: monthly 1950-2004 vs daily futures in the published abstract) — [MIT DSpace](https://dspace.mit.edu/handle/1721.1/114876), [PDF](https://dspace.mit.edu/bitstream/handle/1721.1/114876/Lo_When%20Do%20Stop-Loss.pdf) (secondary snippet; applied to long equity, not short options)
- tastylive (broker-educator; promotional bias): SPX strangle study from 2010, 1 SD strangle sold first trading day of month at about 45 DTE; "managing winners" (close at 50% of max profit) beat holding to expiration; "the vast majority of the profits in the expiration strategy came in the first 25 days" — [tastylive market measures via search](https://www.tastylive.com/shows/market-measures/episodes/mechanically-managing-strangles-08-20-2015) (page not fetchable; secondary snippet; no costs stated)
- tastylive SPY study: hold-to-expiration gives higher average P&L per trade, 50% profit-taking gives higher P&L per day because trades are shorter — [tastylive](https://www.tastylive.com/news-insights/Do-Smaller-Losses-Lead-to-Better-Performance)
- tastylive loss-management: "Managing losers reduces the max loss, but it also reduces the average P/L and win ratio at the same time" (SPY strangles, short puts, short calls) — [tastylive](https://www.tastylive.com/news-insights/Do-Smaller-Losses-Lead-to-Better-Performance)
- Option Alpha (retail educator; promotional): 10-DTE short strangle test, 50% profit target vs hold: higher win rate and lower max drawdown but fewer trades and lower annual return in the reported figures; 60-DTE version with 75% target similar — [Option Alpha](https://optionalpha.com/podcast/when-to-close-option-position) (snippet only)
- CXO Advisory summary of academic-style work on selling S&P 500 puts: profitability of shorting OTM puts "strengthens as expiration nears" but with "large, sharp drawdowns" — [CXO](https://www.cxoadvisory.com/short-selling/when-to-sell-equity-index-put-options/) (secondary; underlying paper not identified)
- Vilkov 2026 tests only entry timing and hold-to-16:00 (no intraday stops/targets): "Hold-to-close only; no dynamic intraday hedging" — [digest limitations](https://github.com/vilkovgr/0dte-strategies). Gamma-risk papers (Dim et al.) argue intraday dynamics are complex but test volatility propagation, not seller exit rules.
- Optimal stopping / dynamic management for short volatility: no theoretical paper located in this session.

### Inferences
- Kaminski-Lo implies a stop on a short option position is value-destroying if the underlying's intraday path is close to a random walk, and useful only if there is short-horizon momentum / vol clustering after a threshold breach; in a short-vol position the stop-out condition (large adverse move) is also when implied vol and spreads are widest, so stop fills are costlier than the mid marks backtests use (inference, not sourced).
- Practitioner "close at 50% profit" results are driven by turnover (P&L per day), not per-trade expectancy; they conflict with per-trade results, so metric choice decides the conclusion.

### Gaps
- No peer-reviewed study of stop-loss / profit-target rules on short index-option spreads with bid-ask costs.
- No study on rolling rules (roll-up/out) for short premium found.
- No optimal-stopping theory for short volatility found.
- tastylive / Option Alpha numbers (win rates, P&L) not retrieved; only qualitative direction from snippets.

---

## 4. Delta / strike selection for short-dated spreads and iron condors

### Takeaway
The only rigorous strike-grid evidence found is Vilkov 2026 (hold-to-close, 0DTE): premium and PnL vary by moneyness, ratio/risk-reversal structures are the only consistently positive-gross ones, and the iron butterfly/condor has a negative long-side mean (positive short-side gross) that costs overwhelm. No delta-bucket study for weekly or Nifty options was found.

### Cited Findings
- Vilkov 2026: strategy results shown across a moneyness grid [0.98, 1.02] step 0.001; "OTM strangles are relatively compact and mostly negative in the upper and lower quartiles, so short strangles outperform in at least 75% of observations"; Table 1 limits to combos with all legs within 1% of ATM — [paper-annotated.md](https://github.com/vilkovgr/0dte-strategies)
- A code file `moneyness_selection.py` exists in the package, but I did not read it — [repo](https://github.com/vilkovgr/0dte-strategies)
- VIX regime: "downside structures earn more in high-VIX"; simple regime filter "not sufficient for implementation" (digest §5.1) — [digest](https://github.com/vilkovgr/0dte-strategies)
- OptionMetrics (via search snippet) backtests writing a 25-delta SPX call every morning at 10 a.m. at the bid, with title implying the covered-call premium is not special but timing is; numbers not retrieved — [OptionMetrics](https://optionmetrics.com/blog/0dte-covered-calls-arent-special-timing-them-is/) (vendor blog; promotional)

### Inferences
- A seller can raise win rate by selling farther OTM, but Vilkov shows costs scale with the number of legs (iron condor B/A cost about 0.025% of spot vs mid mean 0.0073), so wider-wing IC costs matter more for mean than win rate.

### Gaps
- No study of return by delta bucket / probability-OTM for weeklies or Nifty options.
- Short-side strike-bucket P&L from Vilkov's corrected tables not recomputed (data panels in Git LFS, budget exceeded).

---

## 5. Replication, decay, sample dependence and conflicts

### Takeaway
The field is young, mostly working papers, and its flagship positive result has just been retracted for a cost bug; the VRP itself has decayed since about 2010-2012; the retail-loss numbers vary by paper version.

### Cited Findings
- Vilkov retraction (see section 1) — [KNOWN-ISSUES.md](https://github.com/vilkovgr/0dte-strategies). Independent replicator gex.live reproduced the shipped table to four decimals before finding the bug — same file.
- VRP decay: break around 2012 (working paper) or declining since 2010 (survey) — [Dew-Becker](https://www.dew-becker.org/documents/option_decline.pdf), [review](https://dew-becker.org/documents/review.pdf)
- Regime dependence: Vilkov notes some favorable strategy outcomes "may partly reflect the upward drift of the S&P 500 over our sample" and sign changes pre/post 2022 — [paper-annotated.md](https://github.com/vilkovgr/0dte-strategies)
- Beckmeyer versions: $241k/day (Feb 2021-Sep 2023), $350k/day post-May-2022; author posts $184k and $358k for other windows — see section 1.
- Volatility-impact conflict: Dim-Eraker-Vilkov and Adams et al. (secondary) find no destabilising effect; other work (cited in a Princeton thesis abstract) finds a positive link — [Princeton](https://theses-dissertations.princeton.edu/entities/publication/61115cd1-cb09-4a8b-9230-ff488fc2a386).
- Promotional flags: tastylive, Option Alpha, OptionMetrics, Hull Tactical, gex.live-affiliated blogs, and Cboe-sponsored index research (WPUT) all have commercial interest.

### Inferences
- Treat all conditional/ML-timed 0DTE Sharpe ratios as unreplicated; the one clean replication reversed sign.

### Gaps
- Journal-published versions and citation/replication counts for these papers not checked.

---

## 6. Implications for a Nifty weekly-expiry backtester (real-price engine, EOD settle marks only)

### Takeaway
The literature gives no support for a standalone management rule as a source of edge; it supports testing a small set of exit/tenor/strike variants judged on per-trade expectancy and tail, net of true bid-ask costs, with the null expectation that stops cost expected return unless the Nifty path shows short-horizon momentum. This is consistent with the project's existing result (expectancy -177/-238/-348 Rs/lot at 1.0x/1.5x/2.0x slippage, verdict NOT SUPPORTED per CLAUDE.md): the cost-dominated, negative-net pattern in Vilkov's corrected 0DTE table is the closest external analogue (different market, hold-to-close, cost per leg).

### Cited Findings
- (Project context from /home/user/nifty-options-backtester/CLAUDE.md, not external literature) the chain engine prices from NSE F&O bhavcopy settle marks with no bid/ask; intraday stops "would be worse"; expiry-day marks priced at intrinsic.
- External anchors: Vilkov corrected net SR for iron butterfly/condor -2.67 (long structure, mid -0.56) — [KNOWN-ISSUES.md](https://github.com/vilkovgr/0dte-strategies); Kaminski-Lo random-walk stop result — [MIT](https://dspace.mit.edu/handle/1721.1/114876); WPUT ~ PUT Sharpe 0.50 vs 0.52 (10y, gross) — [Indexology](https://www.indexologyblog.com/2016/02/18/paper-by-professor-bondarenko-has-intriguing-new-analysis-of-put-and-wput-indexes/).

### Inferences (testable rules, evidence strength, failure modes)

| # | Rule to test | Evidence from literature | Strength | EOD-only feasible? | Failure modes / what needs intraday data |
|---|---|---|---|---|---|
| 1 | Hold-to-expiry baseline vs 50% profit-take (EOD check) | Practitioner only: profit-take raises P&L per day, hold raises per trade (tastylive SPY); Option Alpha: higher win rate, lower return | Weak (promotional, gross) | Yes, using EOD settle marks | Report per-trade AND per-day-capital metrics; profit-take can appear better purely via turnover; EOD marks miss intrabar touches so fills at target are optimistic; needs bid/ask to charge exit half-spread |
| 2 | Stop-loss at N x credit (EOD-trigger), N in {1, 1.5, 2, 3, none} | Kaminski-Lo: stops lower expected return under random walk, help only with momentum; tastylive: stops cut max loss but lower mean and win rate | Moderate-theory / weak-empirical | Partly: EOD-trigger only | EOD trigger lets gap losses exceed N x; true intraday stop needs 1-min option bars (not in bhavcopy); stop fills at wide spreads on vol spikes; test for adverse-move momentum (does a -1x credit EOD loss predict further loss next day?) as the Kaminski-Lo condition |
| 3 | Time exit (e.g., close at day 3 or 1 DTE) vs hold to expiry | None found directly; 0DTE papers show gamma/tail risk rises as expiry nears (Dim et al. secondary; Vilkov ES1%) | Weak / inferred | Yes | Expiry-day settle is index settlement not option price (project gotcha); intrinsic pricing fine; compare P&L vs tail (ES) not mean only |
| 4 | Entry tenor: 7 DTE vs 3-4 DTE vs 1-2 DTE entry (same delta) | Cboe/Bondarenko: weekly rolling vs monthly similar gross Sharpe; Almeida et al.: day-level VRP large in annualised terms; Vilkov: tiny in % of spot after costs | Conflicting | Yes (DTE grid from archive) | Cost per rupee of premium is higher at short DTE; need quoted spreads (not available); pre/post Tuesday expiry cutover (2025-09-02) and daily-expiry changes are regimes to split |
| 5 | Wing width / leg count: iron condor vs short strangle vs credit spread | Vilkov: IC B/A costs about 0.0251% of spot vs mid mean +0.0073 (short side), i.e. cost > edge; strangle also negative net | Moderate (one source, hold-to-close SPX) | Yes, if cost model per leg is charged | Without bid/ask the engine under-charges legs; test sensitivity at 1.0x/1.5x/2.0x slippage and report break-even slippage |
| 6 | Strike by delta bucket (e.g., 5/10/15/20 delta short strikes) | No academic evidence found; Vilkov grid shows high win rate for OTM strangles with ~zero mean | Weak | Yes | Delta from BS needs IV surface; report P&L/ES not win rate; skew changes the ratio of premium to tail |
| 7 | VIX/IV regime filter (high-VIX only for downside-selling) | Vilkov: "downside structures earn more in high-VIX" but filter "not sufficient"; Dew-Becker: premium decayed | Weak-moderate | Yes (India VIX in repo) | Look-ahead; filter thresholds tuned in-sample; fewer trades -> wide CIs; test on pre/post 2020 split |
| 8 | Kill-switch / drawdown lock (already in repo) vs none | None directly; analogous to stop at portfolio level | Weak | Yes | Absorbing locks bias results (repo has `cross_dd_rearm_days`); compare with and without |

Evaluation protocol suggested by the evidence: (a) report mean per trade, median, ES1%, max drawdown, and worst week, not win rate; (b) charge costs at true size and show the break-even slippage multiple; (c) cluster standard errors by week and apply multiple-testing correction across the exit-rule grid (Vilkov used Benjamini-Hochberg-type corrections); (d) check the cost-unit sanity (Vilkov's bug was mixing percent and fraction scales) with an assertion on cost per lot in rupees; (e) never tune the exit rule on the same weeks used to report the headline; (f) split samples at 2025-09-02 expiry cutover and at the 2020 vol regime.

What needs intraday data (cannot be done on EOD settle marks): true intraday stop/target fills and touch-vs-close differences (Rule 1/2); bid-ask-based exit costs; 11:00-13:00 entry-window fills (project already uses a proxy via 0.40 mid-session alpha and 0.75 slippage scale, which is a modelling assumption, not evidence); gamma/expiry-day behaviour (Rule 3).

### Gaps
- No evidence on Nifty-specific stop-loss or profit-target outcomes; all rules above are hypotheses, not literature findings.
- The evidence strengths in the table are my judgment from the weak/secondary sources above.

---

## Source index (all unverified for full text except Vilkov repo)

| Source | Venue / year | Read |
|---|---|---|
| Vilkov, 0DTE Trading Rules (SSRN 4641356) | WP, Mar 2026; correction Aug 2026 | Full text via author repo: https://github.com/vilkovgr/0dte-strategies |
| Beckmeyer, Branger, Gayda (SSRN 4404704) | WP 2023-24 | Secondary only |
| Dim, Eraker, Vilkov (SSRN 4692190) | WP 2024 | Secondary only |
| Almeida, Freire, Hizmeri (SSRN 4701401) | WP 2024, FMA 2025 | Snippets of abstract |
| Bandi, Fusari, Renò (SSRN 4503344) | WP 2023 | Abstract / seminar pages |
| Adams, Fontaine, Ornthanalai | WP | Quantpedia summary |
| Dew-Becker, Giglio, Le, Rodriguez | JFE 2017 | Snippet |
| Dew-Becker & Giglio decline of VRP / review | WP / ARFE 2024 | Snippet |
| Bondarenko 2016, 2019 | Cboe-sponsored | Secondary summaries |
| Kaminski & Lo | J. Financial Markets 2014 | Secondary snippet |
| SEBI FY25 / FY26 F&O studies | SEBI 2025-26 | News summaries |
| tastylive, Option Alpha, OptionMetrics, Hull Tactical | Promotional / vendor | Snippets only |
| Brogaard-Han-Won; Johannes-Kaeck-Seeger-Shi; Frazzini et al. | - | Not found / not verified |
