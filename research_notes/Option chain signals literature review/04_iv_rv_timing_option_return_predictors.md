# IV-vs-RV spreads and other predictors of option returns: literature for timing short-vol entries

ACCESS NOTE (read first). No full text of any target paper could be retrieved. WebFetch failed with DNS errors (ENOTFOUND) on every host tried: www.cis.upenn.edu, abfer.org, www.cfr-cologne.de, vbn.aau.dk, ideas.repec.org, alphaarchitect.com, www.tuck.dartmouth.edu, api.semanticscholar.org. Direct curl through the agent proxy returned 403 CONNECT-rejected for arxiv.org, api.semanticscholar.org, huggingface.co, and no connection (HTTP 000) for papers.ssrn.com, academic.oup.com, www.sciencedirect.com, www.nber.org, ideas.repec.org, doi.org, core.ac.uk, europepmc.org, researchgate.net. Only github.com answered. All content below therefore comes from WebSearch result summaries, which are model-written secondary summaries of abstracts and snippets. Every paper is marked "abstract/secondary only". No effect sizes (t-stats, Sharpe, cost-adjusted returns) from the four target papers were obtainable, and none are filled from memory. Where a number is quoted it comes from a search summary and is labelled with the document it was attributed to. The search tool also surfaced several arXiv items with 2608.* IDs and a Toronto thesis; I could not open them, so treat them as unverified.

## Q1. Goyal & Saretto (2009), "Cross-section of option returns and volatility", JFE

### Takeaway
The signal is a cross-sectional sort on historical-minus-implied volatility across single stocks; it is not an index-timing signal. Abstract-level evidence says it is large and robust to risk factors and liquidity, but I could not obtain the decile returns, t-stats or cost treatment, so effect size after costs is a gap.

### Cited Findings
- Bibliographic record: Journal of Financial Economics, 2009, vol. 94(2), pp. 310-326, DOI 10.1016/j.jfineco.2009.01.001. Read: abstract/secondary summary only. — [Search summary citing JFE record](https://ideas.repec.org/a/eee/jfinec/v94y2009i2p310-326.html) and [academicnewsletter.sufe.edu.cn listing](https://academicnewsletter.sufe.edu.cn/info/357238) (listed in the search results; pages not opened)
- Design: decile portfolios of straddles and delta-hedged calls and puts, sorted on the difference between historical realized volatility and at-the-money implied volatility. — [Search summary of Goyal-Saretto](https://academicnewsletter.sufe.edu.cn/info/357238)
- Signal construction as reported by a search summary: HV is the standard deviation of daily realized stock returns over the prior twelve months; IV comes from one-month at-the-money options. (Search-summary paraphrase; exact formula and filters not verified.) — [Search results for the paper](https://www.cis.upenn.edu/~mkearns/finread/CrossOptions.pdf) (this is the working-paper PDF listed in the results; I could not open it)
- Headline result (abstract level): a zero-cost strategy long the portfolio with a large positive HV-IV gap and short the one with a large negative gap earns an economically and statistically significant average monthly return; results reported robust to market conditions, stock risk characteristics, industry and option liquidity, and not explained by standard risk-factor models. — [Search summary of the JFE abstract](https://academicnewsletter.sufe.edu.cn/info/357238)
- Sample: one thesis summary says U.S. equity options, 1996-2006. (Secondary; the paper's own sample statement not read.) — [Thesis listed in results](https://osuva.uwasa.fi/server/api/core/bitstreams/91af788a-06d0-46e8-9a17-9e885e484e5b/content)
- Direction in plain terms: later work summarises it as straddle returns and delta-hedged call returns increasing in HV minus IV (i.e. sell options when IV is high relative to HV, buy when low). — [Hu, NUS RMI slides](https://rmi.nus.edu.sg/wp-content/uploads/2020/11/30.-Guanglian-Hu.pdf)
- Single stock vs index: the universe is stock options. A search for index-specific tests turned up no statement that the S&P 500/index options were part of the HV-IV sort result. — see Gaps.
- Cost treatment: secondary only. A 2015 EFMA paper (not Goyal-Saretto) reports long-short straddle returns of roughly 7% to 12% with t-statistics of about 6 to 10 and says the result stays significant when the effective bid-ask spread ratio is 75% or less. This is a different paper's numbers and should not be attributed to Goyal-Saretto. — [EFMA 2015 paper on volatility term structures and option returns](https://efmaefm.org/0efmameetings/efma%20annual%20meetings/2015-Amsterdam/papers/EFMA2015_0530_fullpaper.pdf)
- Extension: volatility-of-volatility has a significant negative relation with equity option returns (Ruan, Journal of Financial Markets, 2020, as reported by the search). — [Ruan VOV paper](https://acfr.aut.ac.nz/__data/assets/pdf_file/0008/185291/157562-X-Ruan-VOV_Option.pdf)

### Inferences
- The HV12m-IV1m spread is conceptually the same object as the user's existing vol_risk_premium / iv_rv features. So Goyal-Saretto gives no NEW feature for the time-series entry model; its value is as evidence that the spread is monotone with straddle returns in the cross-section.
- Because it is a cross-sectional single-stock result on a 1996-2006 sample, transfer to a single-index time-series timing rule (Nifty weekly/monthly) is an extrapolation.

### Gaps
- Decile mean returns, long-short monthly return, t-stats, Sharpe, bid-ask/cost assumptions, subperiod stability: not obtained (full text unreachable).
- Whether any result is reported for index options: not established.
- Decay after 2006: not covered by anything retrieved; see Q5.

## Q2. Cheng (2019), "The VIX premium", RFS

### Takeaway
The paper is about the VIX futures premium (physical forecast of VIX vs futures price), not index-straddle selling, and its key timing-relevant finding is that the premium does NOT rise with risk (it falls or stays flat when risk rises), driven by hedging demand. Predictor-level details beyond the abstract were not obtained.

### Cited Findings
- Bibliographic record: Ing-Haw Cheng (sole author, Dartmouth), Review of Financial Studies 2019, vol. 32(1), pp. 180-227, DOI 10.1093/rfs/hhy062. Read: abstract/secondary only. — [EconBiz record](https://econbiz.de/Record/the-vix-premium-cheng-ing-haw/10012033380); [SSRN abstract 2495414](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2495414)
- Main finding: the ex-ante VIX premium falls or stays flat when ex-ante risk measures rise (the "low premium-response" puzzle); ex-ante premiums predict ex-post VIX futures returns with a coefficient near one; falling premiums precede higher realized market and investment risk. — [Search summary of the SSRN abstract](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2495414)
- A secondary source quotes a coefficient of 0.92 with standard error 0.29 for the premium predicting monthly excess returns to VIX futures. (From a search summary; not verified against the paper.) — [Cheng working paper copy (Toronto TSpace)](https://utoronto.scholaris.ca/bitstreams/682f3c99-5d7d-4dee-b4b4-dafa83785523/download)
- Premium definition: physical forecast of VIX minus the risk-neutral expectation implied by VIX futures; one thesis says the physical forecast is a static ARIMA(2,0,2) fit. — same TSpace link
- Mechanism: falling hedging demand; the premium and dealer net futures positions (CFTC Commitments of Traders) fall together when risk rises. — [Search summary of the SSRN abstract](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2495414)
- Practitioner thesis reading (unverified, thesis not opened): exiting short VIX futures when the estimated premium turns negative lifted Sharpe, "C/S" Sharpe +0.87 vs +0.57 for short-only. — [Toronto TSpace copy of the Cheng paper/thesis hit](https://utoronto.scholaris.ca/bitstreams/682f3c99-5d7d-4dee-b4b4-dafa83785523/download) (provenance of this number is unclear: the summary attributed it to "a Toronto thesis on the VIX premium"; do not cite as Cheng's result)

### Inferences
- The "premium falls when risk rises" result means that high VIX or rising VIX does not imply a fatter premium; naively scaling up short-vol size at high VIX is not supported by this paper. Whether to condition on the premium's sign or level needs the paper's predictive regressions, which I did not read.
- Constructing the premium needs a VIX-futures curve (India VIX futures are thin/nonexistent for this use); the user's spot-based proxies are the closest available analogue, not the same object.

### Gaps
- Sample period, frequency, regression specs, t-stats for the premium as a predictor, and what predicts the premium (beyond hedging demand/dealer positions): not obtained.
- No evidence retrieved that the premium forecast gives a net-of-cost trading rule in the paper itself.

## Q3. Zhan, Han, Cao & Tong (2022), "Option return predictability", RFS

### Takeaway
Single-stock delta-hedged option writing, predicted by firm characteristics (price, profitability, cash holdings, analyst dispersion etc.), reportedly Sharpe above two after costs. It is a cross-sectional single-stock result using characteristics the index does not have, so little is directly usable for timing Nifty.

### Cited Findings
- Bibliographic record: Xintong (Eunice) Zhan, Bing Han, Jie Cao, Qing Tong; Review of Financial Studies 2022, vol. 35(3), pp. 1394-1442, DOI 10.1093/rfs/hhab067. Read: abstract/secondary only. — [IDEAS record](https://ideas.repec.org/a/oup/rfinst/v35y2022i3p1394-1442..html); [PolyU Scholars Hub](https://research.polyu.edu.hk/en/publications/option-return-predictability/)
- Predictors: expected returns to writing delta-hedged calls are negatively correlated with stock price, profit margin and profitability, and positively correlated with cash holding, cash flow variance, new share issuance, total external financing, distress risk and dispersion of analysts' forecasts. — [PolyU Scholars Hub abstract](https://research.polyu.edu.hk/en/publications/option-return-predictability/)
- Performance claim: option portfolio strategies have annual Sharpe ratio above two and remain profitable after transaction costs. — same
- Factor structure: a later abstract version says profits are explained by two option factors and equity risk factors have no explanatory power; predictability is described as still puzzling. — [Search summary of the PolyU/RFS abstract](https://research.polyu.edu.hk/en/publications/option-return-predictability/)
- Relevant to IV-RV timing: results remain significant after controlling for the stock variance risk premium in Fama-MacBeth regressions, i.e. the characteristics carry information beyond the VRP/HV-IV gap. — [OptionMetrics summary / search result](https://optionmetrics.com/research/cao_han__tong_zhan_2020/) (search-summary paraphrase)
- Earlier working-paper versions (Cao, Han, Tong, Zhan 2016) exist at [McGill copy](https://www.mcgill.ca/desautels/files/desautels/option_return_predictability_0.pdf) and [CICF conference copy](http://www.cicfconf.org/sites/default/files/paper_452.pdf); neither could be opened.
- An independent challenge: a Dallas Fed paper, "Are Equity Option Returns Abnormal? IPCA Says No", appears in the search results and argues for a risk-based explanation; I only saw the title, so its findings and its relation to this paper are unverified. — [Dallas Fed WP 2214](https://www.dallasfed.org/-/media/documents/research/papers/2022/wp2214.pdf)

### Inferences
- Firm characteristics have no index analogue. The index-level analogues are aggregate/macro states (earnings dispersion, leverage, distress spreads, FII flow), which are not tested in the paper as retrieved.

### Gaps
- Sample period, exact signal construction, long-short magnitudes, t-stats, trading-cost model (effective spread fraction), subperiod decay, index-vs-stock split: not obtained.

## Q4. Bali, Beckmeyer, Moerke & Weigert (2023), "Option return predictability with machine learning and big data", RFS

### Takeaway
Nonlinear ML on 265 characteristics improves out-of-sample prediction of delta-hedged single-stock option returns, with option-based characteristics as the strongest predictors; net profits are reported positive after costs, but magnitudes and cost parameters were not obtained.

### Cited Findings
- Bibliographic record: Turan G. Bali, Heiner Beckmeyer, Mathis Moerke, Florian Weigert; Review of Financial Studies 2023, vol. 36(9), pp. 3548-3602, DOI 10.1093/rfs/hhad017. Working paper CFR 21-08 and SSRN 3895984. Read: abstract/secondary only. — [SSRN 3895984](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3895984); [Univ. Muenster record](https://www.wiwi.uni-muenster.de/fcm/en/publication/98329575)
- Data: more than 12 million delta-hedged option observations, 1996-2020; 265 option-based and stock-based characteristics as predictors. — [Search summaries of Muenster record and CFR working paper](https://www.cfr-cologne.de/download/workingpaper/cfr-21-08.pdf)
- Models: ridge, lasso, elastic net, gradient-boosted trees, random forests, neural networks (working-paper version). — same CFR link
- Results: nonlinear models improve out-of-sample forecasts over linear ones; monthly out-of-sample R-squared values above 2.5% (working-paper version, per summary); long-short portfolios profitable "even after accounting for transaction costs". — [SSRN abstract summary](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3895984)
- Predictor roles: option-based characteristics are the strongest standalone predictors; stock-based measures add predictive power in combination. — same
- Mechanism: informational frictions and option mispricing (working-paper listing also mentions costly arbitrage). — [EconPapers listing](https://econpapers.repec.org/RePEc:zbw:cfrwps:2108)
- Practitioner write-up exists but could not be opened: [Alpha Architect](https://alphaarchitect.com/using-machine-learning-to-predict-options-returns/).

### Inferences
- The paper supports using tree-based models (consistent with LightGBM) on option-derived features, but gain sources are option-surface features that the user lacks (no chain history).

### Gaps
- Feature-importance ranking (which characteristics dominate), long-short Sharpe, net-of-cost returns, cost assumption, pre/post-2010 decay, any index-option results: not obtained.

## Q5. Timing short-vol using VRP level, VIX percentile, vol-of-vol, trend; replication, decay, conflicts

### Takeaway
What I found is thin and low-grade: a few working papers/theses suggest conditioning on VRP sign or mid-range VIX helps, and one recent working paper finds no timing benefit from a VIX-based scaling. No peer-reviewed, cost-adjusted, index-level timing study was retrieved.

### Cited Findings
- Learning-to-rank VRP harvesting paper (arXiv 2608.24786; unopened, unverified provenance) cites Malkiel et al. (2018) as documenting that conditioning short-put entry on VIX level is associated with higher absolute returns and lower downside risk; reports mid-VIX days (15 to 25) have the strongest regime-conditional Sharpe for five of seven methods, with outer regimes resting on about 20 days each. — [arXiv 2608.24786](https://arxiv.org/html/2608.24786)
- Volatility-managed VRP trading (PKU working paper): variance-swap Sharpe rises from 1.54 to as high as 1.76; VIX futures from 0.61 to as high as 0.78; gains rest on a VRP sign rule rather than a VIX-percentile rule. — [PHBS working paper](https://english.phbs.pku.edu.cn/uploadfile/2024/0530/20240530092144610.pdf)
- Contrary: arXiv 2608.20020 reports that scaling by a standardized index adds no timing alpha; scaled position underperforms unconditional (paired t of -1.85 over 329 months; Sharpe 1.49 unconditional vs 1.36 scaled, noted as inflated by payoff definition). — [arXiv 2608.20020](https://arxiv.org/pdf/2608.20020)
- Term structure and index straddles (Jones/Wang): slope of the equity implied-vol term structure predicts short-horizon straddle returns across stocks, but the slope built from S&P 500 index options has no predictive power for index straddle returns, and no time-series predictability in average straddle returns was found. — [Jones and Wang](https://msbfile03.usc.edu/digitalmeasures/christoj/intellcont/jones_wang-1.pdf)
- Conflict with Cheng: Cheng finds the VIX premium does not rise with risk (see Q2), which cuts against "sell more when vol is high" heuristics; the learning-to-rank result that high-VIX days are weaker is directionally consistent, but samples are tiny. — [Cheng SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2495414)
- Illustrative non-rigorous figure: from 2010 to 2019, VIX averaged around 16% vs realized index vol closer to 12-13% (informal source). — informal source surfaced by search, not opened: [Implied Volatility explainer](https://www.quantt.co.uk/resources/implied-volatility-explained) (do not rely)

### Inferences
- Conflict map: VRP-sign rules show Sharpe gains in short-sample VIX-futures/variance-swap studies; VIX-percentile/standardised scaling shows null or negative timing value in a longer (329-month) test. Net-of-cost, index-option-based evidence is absent from what was retrieved.
- Decay: nothing retrieved quantifies post-publication decay of the Goyal-Saretto or Zhan et al. results; Bali et al.'s sample (to 2020) post-dates both but their subperiod results were not read.

### Gaps
- Malkiel et al. (2018) primary source not located. Cboe PutWrite/BXM conditional-timing studies, Israelov-type practitioner studies, Nifty/India-VIX-specific studies: not found within the call budget.
- No retrieved study tests vol-of-vol or trend conditioning on index short-vol returns net of costs (apart from Ruan's stock-option VOV result).

## Implications for the LightGBM entry-timing model

### Takeaway
The literature confirms the direction of the existing IV-RV spread feature but supplies few new, index-applicable, cost-surviving timing signals; most strong results are single-stock cross-sectional and need chain data or firm data.

### Cited Findings
(Evidence base for each row is in Q1-Q5; strength labels reflect that only abstract-level or unverified evidence was read.)

| Candidate feature or gate | Direction suggested | Evidence strength | Needs chain data the user lacks? |
|---|---|---|---|
| HV(12m) minus ATM IV(1m) spread (already have as vol_risk_premium) | Sell when IV is high relative to HV | Moderate for stocks (Goyal-Saretto, abstract only); index time-series transfer unverified | No |
| Sign of the ex-ante premium (physical vol forecast minus implied), Cheng-style | Skip or reduce when forecast premium non-positive | Weak-moderate: Cheng predicts VIX futures returns (coefficient near one); trading-rule gains come from unverified theses/working papers | No (needs a vol forecast model, e.g. HAR on realized vol); futures curve not needed for a proxy |
| Premium falling while risk rises (change in premium, not level) | Treat falling premium + rising VIX as caution | Weak-moderate (Cheng abstract) | No |
| Mid-range VIX band (about 15 to 25) as a gate | Avoid extremes | Weak: tiny sample, working paper, conflicts with the null scaled-index result | No |
| Vol-of-vol (VVIX analogue, rolling std of India VIX changes) | Higher VOV, lower option returns | Moderate-weak (Ruan, stock options, via search summary) | No for a VIX-based proxy; true VOV from option surface needs chain data |
| Implied-vol term-structure slope | Predictive for stock straddles | Index version is a null result in Jones-Wang, so low priority for Nifty | Yes (needs several expiries; the user's own IV-term spread is partial) |
| Bali et al. option-based characteristics (skew, IV spread, etc.) | Strongest predictors in their ML setup | Moderate for stocks, unknown for index; ranking not read | Yes (full chain history) |
| Zhan et al. firm characteristics | Stock-only | Moderate for stocks | Not applicable to an index; macro analogues only |

### Inferences
- Priority order given the evidence: (1) keep HV-IV spread and add a forecast-based expected-RV premium (HAR-type) as a replacement for naive trailing HV; (2) add change-in-premium and a VIX-of-VIX proxy; (3) treat VIX-band gates as hypotheses to test out-of-sample rather than priors; (4) defer chain-based features until archive/chain data covers them.
- Because LightGBM already uses the spread, treat any new feature as valid only if it improves walk-forward AUC and net P&L under realistic costs, given the CLAUDE.md finding that real-price chain expectancy is negative (-177 Rs/lot at 1.0x slippage). The literature gives no basis to expect a timing filter to rescue negative net expectancy.

### Gaps
- Net-of-cost magnitudes for every row above are unknown from this research; verifying them requires access to the full texts (SSRN/OUP/ScienceDirect blocked here). Recommended next step: obtain PDFs of the four papers offline and re-extract the tables for HV-IV deciles, costs, feature importance and subperiod splits.
