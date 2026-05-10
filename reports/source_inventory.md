# Source Inventory

Recommended acquisition order:
1. CDSL daily/archive for final FPI/FII daily cash flows.
2. NSE current APIs for current-day DII and provisional combined FII/FPI.
3. NSDL latest page as a same-day validator for final FPI/FII.
4. CDSL fortnightly sector-wise pages for direct sector data and a derived daily proxy.
5. FYERS and third-party adapters remain optional and non-primary.

## cdsl

- Trust tier: official
- History coverage: daily archive links and monthly equity trade ZIPs from 2003 onward; sector-wise fortnightly pages available
- Granularity: daily and fortnightly
- Participant coverage: FII/FPI
- Sector data: direct fortnightly sector-wise investment; daily sector proxy feasible
- Implementation difficulty: medium
- Fragility risk: medium
- URLs: https://www.cdslindia.com/Publications/ForeignPortInvestor.html, https://www.cdslindia.com/Publications/FIITrends.aspx, https://www.cdslindia.com/Publications/EquityDataFII.html, https://www.cdslindia.com/eservices/Publications/FIICalendar, https://www.cdslindia.com/publications/FII/FortnightlySecWisePages/March%2031%2C%202026.html
- Limitations:
  - No DII series.
  - Archive page is ASP.NET and requires form POSTs for arbitrary dates.
  - Monthly trade ZIP files are large.
  - Archive-form retrieval still appears broken for historical per-date XLS fetches.
  - ZIP reconstruction now has official transaction-code documentation, but still needs filters for amendments/deletions/reporting semantics before it can be treated as production-grade daily history.

## sebi_fpi_statistics

- Trust tier: official
- History coverage: FPI trade-wise equity archive from 2003 onward, plus pre-2014 archive and sector/statistics links
- Granularity: trade-wise monthly files, daily latest/current month pages, monthly historical statistics
- Participant coverage: FII/FPI
- Sector data: direct fortnightly sector-wise links
- Implementation difficulty: medium
- Fragility risk: low
- URLs: https://www.sebi.gov.in/statistics/fpi-investment.html, https://www.sebi.gov.in/statistics/fpi-investment/trade-wise-equity-data-of-fpi.html, https://www.sebi.gov.in/statistics/fpi-investment/archive.html, https://www.sebi.gov.in/statistics/fpi-investment/fortnightly-sector-wise.html
- Limitations:
  - No direct DII series.
  - Trade-wise data requires reconstruction logic from transaction codes and reporting fields.
  - Since June 01, 2014 SEBI points users to NSDL/CDSL for daily dissemination rather than hosting a date-query daily API itself.

## nse_current

- Trust tier: official
- History coverage: latest day only
- Granularity: daily
- Participant coverage: FII/FPI, DII
- Sector data: none
- Implementation difficulty: low
- Fragility risk: low
- URLs: https://www.nseindia.com/reports/fii-dii, https://www.nseindia.com/api/fiidiiTradeReact, https://www.nseindia.com/api/fiidiiTradeNse
- Limitations:
  - Official NSE endpoint exposes only latest day.
  - NSE page states FII/FPI values are provisional.

## nsdl_latest

- Trust tier: official
- History coverage: latest daily page verified; older history not discovered via simple URL pattern
- Granularity: daily
- Participant coverage: FII/FPI
- Sector data: none
- Implementation difficulty: medium
- Fragility risk: medium
- URLs: https://pilot.fpi.nsdl.co.in/Reports/Latest.aspx
- Limitations:
  - ASP.NET page requires HTML parsing.
  - Historical archive path is not obvious from the public latest page.

## fyers

- Trust tier: semi_official
- History coverage: not confirmed for historical institutional-flow API
- Granularity: unknown
- Participant coverage: unknown
- Sector data: unknown
- Implementation difficulty: high
- Fragility risk: high
- URLs: https://myapi.fyers.in/
- Limitations:
  - No documented FYERS institutional-flow API was confirmed during discovery.
  - Web/UI presence should not be assumed to imply stable machine access.
  - Support content describes FII/DII as a platform analytics feature, not a public API.

## third_party_moneycontrol

- Trust tier: third_party
- History coverage: at least multi-year monthly FII/DII activity pages were discoverable in search results
- Granularity: monthly confirmed from crawled snippets; daily/API availability not yet validated
- Participant coverage: FII/FPI, DII
- Sector data: appears to expose FPI sectoral activity pages
- Implementation difficulty: medium
- Fragility risk: high
- URLs: https://www.moneycontrol.com/india/stockmarket/foreigninstitutionalinvestors/17/12/activity/FII
- Limitations:
  - Not official.
  - Search/crawl snippets confirm useful history, but endpoint stability and structured exportability are still unverified.
  - Use only with explicit provenance flags and only if official DII history remains unavailable.

## fallback_third_party

- Trust tier: third_party
- History coverage: user-supplied
- Granularity: user-supplied
- Participant coverage: user-supplied
- Sector data: user-supplied
- Implementation difficulty: low
- Fragility risk: high
- URLs: n/a
- Limitations:
  - Disabled by default.
  - All rows must be tagged as third-party provenance.
