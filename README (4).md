# Housing affordability in Europe

Panel of 31 countries × 2010–2025 × 22 age groups × 3 sexes (≈ 32,000 rows, 20 variables).

## Datasets

- Eurostat house price index (`prc_hpi_a`): https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/prc_hpi_a/A.TOTAL.I15_A_AVG.?format=SDMX-CSV
- Eurostat mean and median income (`ilc_di03`): https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/ilc_di03/A....EUR.?format=SDMX-CSV
- ECB mortgage rates, house purchase (`MIR`): https://data-api.ecb.europa.eu/service/data/MIR/M..B.A2C.A.R.A.2250.EUR.N?format=csvdata
- ECB HICP consumer prices (`ICP`): https://data-api.ecb.europa.eu/service/data/ICP/M..N.000000.4.INX?format=csvdata

## Run

```powershell
uv sync
uv run merge_housing_affordability.py
```

The script downloads the files to `raw/` and writes `housing_affordability_panel.csv`. If the download is
blocked, save the four links above into `raw/` as `eurostat_prc_hpi_a.csv`, `eurostat_ilc_di03.csv`,
`ecb_mir_house_purchase.csv` and `ecb_icp_hicp.csv`, then run it again.

Options: `--start`, `--end`, `--base-year` (default 2015), `--refresh`.

## Variables

| Variable | Description |
|---|---|
| `country_code` | Eurostat country code |
| `country` | Country name |
| `region` | Northern, Western, Southern or Eastern Europe |
| `euro_area` | Whether the country used the euro that year (yes/no) |
| `year` | Calendar year |
| `age_group` | Age group (groups overlap, e.g. 18-64 includes 25-49) |
| `sex` | Total, Male, Female |
| `median_income_eur` | Median equivalised net income, EUR per year |
| `mean_income_eur` | Mean equivalised net income, EUR per year |
| `house_price_index` | House price index (2015 = 100) |
| `hicp_index` | Consumer price index (2015 = 100) |
| `mortgage_rate_pct` | Interest rate on new mortgages, % (euro-area countries only) |
| `house_price_growth_pct` | House price change vs previous year, % |
| `income_growth_pct` | Median income change vs previous year, % |
| `inflation_pct` | Consumer price change vs previous year, % |
| `real_house_price_index` | House prices adjusted for inflation (base year = 100) |
| `real_income_index` | Income adjusted for inflation (base year = 100) |
| `price_to_income_index` | House prices relative to income (base year = 100; above 100 = less affordable) |
| `mortgage_payment_to_income_index` | Monthly payment on a 25-year loan relative to income (base year = 100; above 100 = less affordable) |
| `affordability_vs_prev_year` | Whether the payment index rose ("less affordable") or fell ("more affordable") |
