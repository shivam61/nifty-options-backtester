# Indian and emerging-market academic evidence on options, India VIX, VRP and option-chain signals

**Access limitation (read first).** Only github.com was reachable in this session. WebFetch returned DNS errors (ENOTFOUND) and the egress proxy returned 403 on CONNECT for the other hosts I probed. Unreachable: osuva.uwasa.fi, emerald.com, studentlive.iimcal.ac.in, sebi.gov.in, dspace.kaist.ac.kr, moneylife.in, arxiv.org, papers.ssrn.com, ideas.repec.org, doi.org, nseindia.com, researchgate.net, sciencedirect.com, springer.com, tandfonline.com, business-standard.com, nism.ac.in, semanticscholar.org, crossref.org, openalex.org, core.ac.uk, iima.ac.in. No full text of any paper was read. Every finding below comes from WebSearch result summaries, which are secondary and machine-generated. Treat all numbers as "as reported by the search summary" and re-verify against the primary documents before relying on them. Sources were never opened by me. Citation URLs are the result URLs returned by search.

Not found or not searched: Sehgal & Vijayakumar 2009, Narain/Nigam/Pandey 2016, and any Indian "max pain" paper. I did not search for them by name, so I know nothing about them from this session. The Bank Nifty PCR study (Singh & Chaudhary) surfaced only as a search snippet, with no title or year.

## 1. Pricing efficiency, mispricing, implied-volatility smile/skew and tail pricing in Nifty options

### Takeaway
The Indian studies the search turned up are mostly old, small-sample or descriptive. They agree on a smile or smirk and report volatility under-priced in 2001-02. I found no rigorous modern Nifty test of skew-premium harvesting.

### Cited Findings
- Varma (2002), "Mispricing of Volatility in the Indian Index Options Market", IIM Ahmedabad working paper. Per the search summary, it uses closing Nifty futures and options prices from June 2001 to February 2002. It estimates the implied risk-neutral distribution with the Breeden-Litzenberger formula applied to estimated implied-volatility smiles. The implied distribution is "more sharply peaked and, with one exception, has thinner tails than the normal or historical distribution". A secondary citing summary says Varma found "severe mispricing" and volatility "severely under-priced", even after using futures to remove the effect of cash-market short-sale restrictions. Level read: search summary only. [IIMA listing](https://www.iima.ac.in/publication/mispricing-volatility-theindian-index-options-market); [ResearchGate](https://www.researchgate.net/publication/229027736_Mispricing_of_volatility_in_the_Indian_index_options_market); [AAMJAF 2008, a citing paper](https://ejournal.usm.my/aamjaf/article/download/aamjaf_vol4-no1-2008_3/pdf/641)
- Shaikh & Padhi, "Stylized patterns of implied volatility in India: a case study of NSE Nifty options", Emerald JIBR. The year and authors are inferred from the result listing (DOI JIBR-12-2013-0103) and an EconBiz record naming "Shaikh Imlak". Only the title surfaced, with no content. [Emerald](https://www.emerald.com/insight/content/doi/10.1108/JIBR-12-2013-0103/full/html); [EconBiz](https://www.econbiz.de/Record/stylized-patterns-of-implied-volatility-in-india-a-case-study-of-nse-nifty-options-shaikh-imlak/10014875197)
- An Nifty 50 study ("Implied Volatility Smile Patterns: Evidence from Nifty 50 Index Options", IJSSER 3(12)) reports a classic U-shaped smile, a tendency to smirk in 30-day options, and higher implied volatility for shorter maturities. A regression-based study attributes the higher implied volatility of deep in/out-of-the-money options to liquidity: sellers demand a liquidity premium. Level: search summary only. The second study's citation was not captured. [ResearchGate](https://www.researchgate.net/publication/343263957_Implied_Volatility_Smile_Patterns_Evidence_from_Nifty_50_Index_Options_International_Journal_of_Social_Science_and_Economic_Research_312_6851-6882); [Management Dynamics](https://managementdynamics.researchcommons.org/cgi/viewcontent.cgi?article=1205&context=journal)
- A 2024 Springer paper, "Effectiveness of deterministic option pricing models: new evidence from Nifty and Bank Nifty Index options", reports that implied volatility rises from ATM toward both deep OTM and deep ITM, confirming a smile/smirk in both indices. Level: search summary only. [Springer](https://link.springer.com/article/10.1057/s41260-024-00348-1)

### Inferences
- Varma's 2001-02 finding of under-priced volatility and thin implied tails may be a 2001-02 artefact (new market, short sample). It is not evidence for the 2019+ market, and could be tested with the NSE archive.
- Liquidity explains wing implied volatility, so OTM wing "richness" may be an illiquidity premium rather than harvestable edge. This is consistent with the project's chain-engine result (negative expectancy with real settles), but the link is an inference.

### Gaps
- Sehgal & Vijayakumar 2009 and Narain/Nigam/Pandey 2016 not retrieved or searched by name.
- No effect sizes, t-stats or sample periods for the smile papers.
- No study found that tests whether Nifty skew predicts returns or whether skew-based trades are profitable.

## 2. India VIX forecasting power and variance/volatility risk premium in India

### Takeaway
Direct, quantified Indian VRP evidence is thin in what I could reach. The one rigorous academic item found (Chakrabarti & Kumar 2017) is about order-flow demand affecting VRP changes, not about the average premium level. The newer SSRN preprints (not peer reviewed) point to a positive raw VRP that does not survive costs and tail losses.

### Cited Findings
- IIM Calcutta working paper 688 (authors and year not captured) compares GARCH against India VIX for predicting Nifty 50 volatility, using realised volatility from high-frequency data as the benchmark, evaluated by MAE and RMSE. The search summary did not include results, so which model won is unknown. [wps_688](https://studentlive.iimcal.ac.in/sites/all/files/pdfs/wps_688.pdf)
- Chakrabarti & Kumar (2017), Multinational Finance Journal: examines whether vega-weighted order imbalance in Nifty index options moves the variance risk premium. Reported: volatility demand significantly affects changes in the VRP, and demand for the most expensive options has the largest effect. Level: search summary only. [Univ. of Vaasa listing](https://sites.uwasa.fi/mfjuva/?p=2597)
- Agarwal, "The Variance Risk Premium in Nifty 50: A Structural Anatomy Across Nine Empirical Filters" (SSRN, preprint, date not captured): VRP positive on 74.9% of trading days; also reports a "structural epoch inversion" in early 2026. Level: abstract-style snippet only. [SSRN 6530119](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6530119)
- Several IIM-type and thesis items on VRP appeared in results (a Erasmus thesis "An Analysis of the use of Volatility Risk Premium Strategies in the ..." and a Medium post). I did not extract content. [thesis.eur.nl](https://thesis.eur.nl/pub/73344/598210.pdf)

### Inferences
- Positive VRP on 74.9% of days is a hit-rate statistic. It says nothing about the mean after tail losses, so it is not inconsistent with the net-of-cost negative results in section 3.

### Gaps
- No India VIX vs realised-volatility regression (slope, R-squared, bias) obtained. WPS 688 result not read.
- No mean VRP level (vol points) for Nifty from a peer-reviewed source.
- Did not locate Indian VIX-forecasting papers from Journal of Emerging Market Finance, Vikalpa or IIMB Management Review.

## 3. Strategy profitability on Nifty (straddle, strangle, short volatility) and SEBI F&O outcome studies

### Takeaway
Everything I could reach points the same way: net of realistic costs, mechanical short-volatility and straddle strategies on Nifty lose money in the samples tested. The one contrary item (a strangle paper) reports relative rather than net-of-cost results, and I saw only its abstract. SEBI data show most retail traders lose, with option sellers losing less often but in larger rupee amounts.

### Cited Findings
- Kumar, Lalit (2025), University of Vaasa master's thesis on long vs short initial delta-neutral straddles on Nifty 50. Per the search summary: compared using Sharpe ratio, maximum drawdown, paired t-tests, ANOVA and India VIX regressions. Both straddles ended with negative Sharpe ratios; no statistically significant difference between long and short across market regimes; VIX explained only a small share of performance. Sample period, hedging frequency, costs, exact Sharpe values and limits could not be retrieved (the PDF host osuva.uwasa.fi was unreachable). The mapping of the exact bitstream to this thesis is from the search summary, not verified. [osuva bitstream 8a34262d](https://osuva.uwasa.fi/server/api/core/bitstreams/8a34262d-fdad-4af1-8f84-34f088e86a3a/content)
- Pillai (SSRN, June 2026 per search summary), "Trading the Volatility Risk Premium on Nifty 50: Strategy Backtest with Realistic Frictions": 119 monthly expiry cycles, January 2015 to April 2025. Cost model reported as 0.05% STT on the sell side, 0.03% brokerage per leg, 0.5% slippage, plus futures rebalancing costs for the delta-hedged variant. Net of all costs every strategy has negative annualised return. Least bad: put-write at 0.94 moneyness, about -0.9% annualised, Sharpe -0.37. Straddle variants lost roughly 44-45% per year. Author attributes the losses mainly to tail risk, with transaction costs "secondary"; single-month drawdowns reached -13.2% of margin for straddles. Independent author, preprint, not peer reviewed; abstract level only. [SSRN 6876580](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6876580)
- "Strangle to resuscitate: evidence from India", Journal of Investment Strategies: Nifty monthly data 2007-2019; long vs short strangles over three legs. Reported: short strangle beats long on success rate, profitability, risk and return at every leg; the third leg shows lower risk and higher return than the other two short-strangle legs; regression analysis supports this. Abstract/highlights only; costs and methodology unchecked. This contradicts the two negative-return items above only if costs are ignored, which I could not verify. [risk.net](https://www.risk.net/journal-of-investment-strategies/7721271/strangle-to-resuscitate-evidence-from-india)
- SEBI FY25 study (July 2025), via press: about 91% of individual derivatives traders net-lost in FY25 (top 13 brokers, around 96 lakh unique traders); aggregate net loss about Rs 1,05,603 crore versus Rs 74,812 crore in FY24 (+41%) after transaction costs; average loss about Rs 1.1 lakh versus Rs 86,728; losses concentrated in weekly index options (Nifty 50, Sensex, Bank Nifty, Bankex). A later summary cites a revised FY25 estimate of Rs 1,11,788 crore, so the figure varies by vintage. Secondary reports only; the sebi.gov.in report was not reachable. [Business Standard](https://www.business-standard.com/amp/markets/news/net-losses-of-traders-in-fo-widens-in-fy25-sebi-study-125070701221_1.html); [Value Research](https://www.valueresearchonline.com/stories/225398/average-trader-lost-rs-1-1-lakh-fo-fy25/); [corplawupdates](https://www.corplawupdates.in/updates/sebi-equity-derivatives-retail-trader-study-fy26)
- SEBI FY25-FY26 studies (PR No. 50/2026, report dated August 2026, per search summaries): 87.7% of traders net lost in FY26, versus 90.9% the year before; aggregate losses Rs 91,685 crore in FY26; options about 92% of aggregate individual losses. Behaviour study sample is a random 5,050 traders from about 1.23 crore. In FY26, about 90% of "Only Options Buyers" and 75% of "Majorly Options Buyers" were loss-makers; "Majorly Options Sellers" had 44% loss-makers (51% in FY25) but the group was net negative (Rs 543 crore in FY26, Rs 428 crore in FY25); losing sellers averaged about Rs 51.7 lakh versus Rs 4.6 lakh (majorly buyers) and Rs 1.3 lakh (only buyers). A commentary counts 105 major sellers in FY26, 46 of whom lost. SEBI itself cautions on small categories. [SEBI report PDF](https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1787233601328.pdf); [openthemagazine](https://openthemagazine.com/business/sebi-fo-loss-study-explained-why-9-in-10-retail-traders-lost-91685-crore-in-fy26); [futuresenseindia](https://futuresenseindia.com/news/individual-traders-equity-derivatives-losses-sebi-study/); [Substack critique](https://raviv2107.substack.com/p/sebis-derivatives-study-useful-data)
- "Animal Spirits on Steroids: Evidence from Retail Options Trading in India" (Univ. of Alberta PDF, authors given as Vikas Agarwal et al. by URL only): cites a 1.25% spread for NIFTY 50 options from Bhat, Pandey and Rao, and estimates spread costs at 48% of total losses on index options, with the caveat that actual spread data were unavailable to the authors (back-of-envelope). [PDF](https://www.ualberta.ca/en/finance-department/media-library/documents/vikas-agarwal.pdf)

### Inferences
- Sellers' lower loss frequency with larger rupee losses fits a negative-skew payoff (frequent small wins, rare large losses), matching Pillai's tail-risk attribution. Both are secondary reports, so this is a hypothesis.
- The two negative academic backtests use monthly expiries (Pillai) and an unspecified sample (Vaasa). The project trades weekly and monthly, so neither maps one-to-one.

### Gaps
- Vaasa thesis: sample period, data source, hedging frequency, cost assumptions, exact Sharpe values, and limitations not retrieved.
- Pillai: full method and robustness unverified; a one-author preprint.
- Strangle paper: cost treatment unknown.
- SEBI primary reports not read; numbers from press.
- No academic study found on covered calls or iron condors on Nifty.

## 4. Information content of Nifty open interest, put-call ratio and volume

### Takeaway
I found no peer-reviewed long-sample test of Nifty OI-based PCR predicting index direction or volatility. What surfaced is generic or non-Indian, plus one skeptical Bank Nifty snippet.

### Cited Findings
- MDPI *Economies* 7(1):24, "Put-Call Ratio Volume vs. Open Interest in Predicting Market Return: A Frequency Domain Rolling Causality Analysis". Per summary: short-run causality from volume-PCR and OI-put ratio to market returns; notes few studies use the OI version. The market studied was not stated in the snippet, so it is not shown to be Indian. [MDPI](https://www.mdpi.com/2227-7099/7/1/24)
- An Indian Bank Nifty study (authors given as Singh and Chaudhary in the summary; no title or year) is described as more skeptical: regression explained at most about half of underlying returns, predictability weaker for index than stock options, only one year of data. The "half" wording is unclear in the snippet. Citation unverified, snippet only; no URL for the paper itself surfaced.
- US work cited in the same summary treats daily stock-option PCR as contrarian (negatively related to next-day return). [Harbourfront Quant Substack](https://harbourfrontquant.substack.com/p/is-the-put-call-ratio-a-reliable)
- Taiwan: "Low risk, high return: Improving option writing performance with put-call ratios in Taiwan" (ScienceDirect, 2025). Unconditional Sharpe (Sortino) ratios for buy-write, put-write, covered combo and delta-hedged strategies are 0.48 (0.71), 0.55 (0.87), 0.58 (0.84) and 0.15 (0.29). Writing only when the put-call ratio is low gives 0.71 (1.03), 0.86 (1.29), 0.79 (1.14), 0.78 (1.12). Summary only. This is the only quantified PCR-conditioned option-writing result I found. [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0927538X25000241)

### Inferences
- The Taiwan result is a candidate test design for Nifty (condition short-vol entries on PCR) and is the closest evidence that option-chain PCR timing might help sellers. It is untested in India.

### Gaps
- No Indian paper retrieved on OI changes, max pain, or option volume as predictors; "max pain" academic literature not found.
- The MDPI paper's market and sample are unknown.
- No evidence on OI/PCR as a volatility predictor in India.

## 5. Other emerging markets: KOSPI200, Taiwan, China, Hong Kong, Brazil

### Takeaway
Evidence is mixed. KOSPI200 shows no ATM volatility risk premium (OTM puts show negative delta-hedged gains). China SSE 50 ETF options show a positive VRP. Taiwan work centres on retail dominance and institutional hedging demand. Hong Kong and Brazil returned nothing.

### Cited Findings
- Park (2009), "The Volatility Risk Premium in the KOSPI200 Index Options", *Journal of Derivatives and Quantitative Studies* (Emerald; volume 17(2), p. 67 per the URL). Using Bakshi & Kapadia delta-hedging, no volatility risk premium for ATM options ("contrary to the S&P 500 market"). Delta-hedged gains of OTM and put options are negative and significant; attributed to overpriced puts or microstructure factors such as wide bid-ask spreads. The author name, year and attribution come from the search summary, not from the page. Abstract level only; no t-stats captured. [Emerald](https://www.emerald.com/jdqs/article/17/2/67/205260/The-Volatility-Risk-Premium-in-the-KOSPI200-Index)
- Yoon & Byun (2009), *Journal of Futures Markets* (per summary): volatility risk does not require a premium in KOSPI200 options; jump fears matter. Related KAIST record "Is volatility risk priced in the KOSPI 200 index options market?". Summary only. [KAIST](https://dspace.kaist.ac.kr/handle/10203/98834?mode=full)
- Yoon & Kim, "Leading and Following Variance Risk Premiums: Evidence from S&P500 and KOSPI200 Options", JDQS 22(1): listed, findings not retrieved. [Emerald issue page](https://emerald.com/insight/publication/issn/1229-988X/vol/22/iss/1)
- China: "Variance Risk Premium and Return Predictability: Evidence from the Chinese SSE 50 ETF Options" reports a strong variance risk premium, delta-hedged portfolios consistent with investors paying to hedge variance risk, and predictive power mainly from the upside VRP. A 2022 study on 2016-2021 data reports the implied-volatility risk premium verified. SSE 50 ETF options launched in February 2015. Summary only. [ResearchGate](https://www.researchgate.net/publication/335018450_Variance_Risk_Premium_and_Return_Predictability_Evidence_from_the_Chinese_SSE_50_ETF_Options); [Wiley Complexity 2022](https://onlinelibrary.wiley.com/doi/10.1155/2022/6813797)
- Taiwan: retail dominates TAIEX options; one study reports negative skew driven by institutional demand for downside protection and that selling OTM puts yielded higher profitability than calls. A conference paper on TAIEX option returns lists volatility-risk factors that reduce returns (numbers like 7.806%, 6.336%, 1.294% per year; meaning unclear from the snippet). [Springer chapter](https://link.springer.com/chapter/10.1007/978-3-319-99993-7_10); [ScienceDirect, TAIFEX smile](https://www.sciencedirect.com/science/article/abs/pii/S1059056011000311)
- Retail clientele (US stocks, not EM): higher retail share goes with lower delta-hedged option returns, interpreted as a lottery premium paid by retail buyers. Choy, SSRN. [SSRN 1577942](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1577942)

### Inferences
- Where retail participation is heavy and costs high (KOSPI200 in the 2000s, Taiwan, India), results differ by market. Retail buying demand could create a premium for sellers, but wide spreads and jump risk erode it. This is an inference from different papers, not a tested claim.

### Gaps
- Hong Kong (HSI) and Brazil: no results found. Not covered.
- KOSPI200: no t-stats, sample dates or frequency retrieved.
- No source found that directly reconciles retail participation with the sign of the VRP across emerging markets.

## 6. Indian options microstructure: bid-ask, liquidity by strike, STT

### Takeaway
Very little retrieved. The only Indian spread number is a 1.25% Nifty option spread from a citing paper, with an unverified claim that spreads account for 48% of retail index-option losses.

### Cited Findings
- The Alberta paper cites 1.25% as the NIFTY 50 option spread (Bhat, Pandey and Rao) and estimates spread costs at 48% of total index-option losses; the authors state spread data were not available to them. [PDF](https://www.ualberta.ca/en/finance-department/media-library/documents/vikas-agarwal.pdf)
- Pillai uses 0.05% sell-side STT, 0.03% brokerage per leg, 0.5% slippage (see section 3). [SSRN 6876580](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6876580)
- Deep ITM and OTM Nifty options are illiquid and priced with a liquidity premium (see section 1).

### Inferences
- A 0.5% slippage assumption and a 1.25% quoted spread are both large relative to premia on far-OTM weekly options, so cost and slippage sensitivity matters most for the project's weekly track.

### Gaps
- No academic or regulatory paper on STT impact (including the 2024 STT hike), strike-level liquidity, or intraday spread patterns (the 11:00-13:00 window assumption is untested here).
- The Bhat/Pandey/Rao paper is not identified.

## Transferability to Nifty

Evidence quality is low: no full text read, secondary summaries only. Classification below is provisional.

**Supported in Indian data (provisional)**
- Implied-volatility smile/smirk, with wings partly explained by illiquidity (sources in section 1).
- Retail F&O losses: SEBI data show about 88-91% of individual traders net-lose; losses concentrated in weekly index options (section 3).
- Mechanical short-vol and straddle strategies lose money net of realistic costs in Pillai's 2015-2025 monthly sample (section 3). This matches the project's chain-engine result (expectancy -177/-238/-348 Rs/lot), which is the project's own data and not a literature source.

**Contradicted or in tension with US findings**
- The US finding of a robustly positive, harvestable VRP is not supported net of costs in the Indian preprint evidence, and ATM VRP was absent in KOSPI200 (Park 2009).
- Short strangle outperforming long strangle (Journal of Investment Strategies, 2007-2019) conflicts with the negative net-of-cost results, unless costs or the sample explain it. Unresolved.
- SEBI: sellers lose less often than buyers (44% vs 75-90% loss-makers) but still lose in aggregate.

**Untested or not found in Indian data**
- India VIX as a forecaster of realised volatility (WPS 688 result unread).
- OI, PCR or max-pain information content for direction or volatility.
- Skew-based signals, tail underpricing after 2002, PCR-conditioned option writing (Taiwan precedent only).
- Hong Kong, Brazil.

**Concrete tests to run (using the project's NSE archive and chain engine)**
1. Regress realised 30-day Nifty variance on India VIX variance (2019-2026). Report slope, intercept, R-squared and mean VRP in vol points, by expiry week and regime.
2. Delta-hedged-gain tests (Bakshi-Kapadia) by moneyness and by put vs call on archive settles, to compare with Park 2009 and see whether ATM VRP is zero.
3. Replicate Pillai's grid (cost 0.05% STT, 0.03% brokerage, 0.5% slippage) and the Taiwan PCR-conditioned writing test: enter short-vol only when OI-PCR is in the low tercile; compare Sharpe with unconditional, with 1.0x, 1.5x and 2.0x slippage.
4. Predictive regressions: next-day and next-week Nifty return and realised vol on OI-PCR, OI change at max-pain strikes, and volume-PCR, with Newey-West errors and out-of-sample splits.
5. Cost sensitivity: scale slippage to a 1.25% spread and check whether net expectancy changes sign.
6. Tail check: report worst single-month loss as a share of margin and compare with Pillai's -13.2%.
7. Re-estimate Varma's risk-neutral tail test on 2019+ data to see whether the 2001-02 under-priced-volatility finding persists.

Sources are linked inline. The findings still need primary-source verification.
