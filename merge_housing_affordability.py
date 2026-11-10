from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    print("Tip: if downloads fail with CERTIFICATE_VERIFY_FAILED, run:  uv pip install truststore")

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
LOAN_YEARS = 25

EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/{ds}/{key}?format=SDMX-CSV"
ECB = "https://data-api.ecb.europa.eu/service/data/{ds}/{key}?format=csvdata"

DOWNLOADS = {
    "eurostat_prc_hpi_a.csv": [EUROSTAT.format(ds="prc_hpi_a", key="A.TOTAL.I15_A_AVG.")],
    "eurostat_ilc_di03.csv": [EUROSTAT.format(ds="ilc_di03", key="A....EUR.")],
    "ecb_mir_house_purchase.csv": [ECB.format(ds="MIR", key="M..B.A2C.A.R.A.2250.EUR.N")],
    "ecb_icp_hicp.csv": [ECB.format(ds="ICP", key="M..N.000000.4.INX")],
}

COUNTRIES = {
    "AT": ("Austria", "Western", 1999), "BE": ("Belgium", "Western", 1999), "BG": ("Bulgaria", "Eastern", 2026),
    "CY": ("Cyprus", "Southern", 2008), "CZ": ("Czechia", "Eastern", None), "DE": ("Germany", "Western", 1999),
    "DK": ("Denmark", "Northern", None), "EE": ("Estonia", "Northern", 2011), "EL": ("Greece", "Southern", 2001),
    "ES": ("Spain", "Southern", 1999), "FI": ("Finland", "Northern", 1999), "FR": ("France", "Western", 1999),
    "HR": ("Croatia", "Southern", 2023), "HU": ("Hungary", "Eastern", None), "IE": ("Ireland", "Northern", 1999),
    "IT": ("Italy", "Southern", 1999), "LT": ("Lithuania", "Northern", 2015), "LU": ("Luxembourg", "Western", 1999),
    "LV": ("Latvia", "Northern", 2014), "MT": ("Malta", "Southern", 2008), "NL": ("Netherlands", "Western", 1999),
    "PL": ("Poland", "Eastern", None), "PT": ("Portugal", "Southern", 1999), "RO": ("Romania", "Eastern", None),
    "SE": ("Sweden", "Northern", None), "SI": ("Slovenia", "Southern", 2007), "SK": ("Slovakia", "Eastern", 2009),
    "IS": ("Iceland", "Northern", None), "NO": ("Norway", "Northern", None), "CH": ("Switzerland", "Western", None),
    "UK": ("United Kingdom", "Northern", None),
}
ECB_TO_EUROSTAT_GEO = {"GR": "EL", "GB": "UK"}

INCOME_CODES = {
    "median_income_eur": (["MED_E", "MED"], "MED"),
    "mean_income_eur": (["MEI_E", "MEAN"], "MEAN"),
}
META_COLUMNS = {"DATAFLOW", "LAST UPDATE", "TIME_PERIOD", "OBS_VALUE", "OBS_FLAG", "CONF_STATUS"}


def download(refresh: bool) -> None:
    RAW.mkdir(exist_ok=True)
    for name, urls in DOWNLOADS.items():
        target = RAW / name
        if target.exists() and not refresh:
            print(f"[skip] {name} already downloaded")
            continue
        for url in urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "housing-affordability/3.0"})
                with urllib.request.urlopen(req, timeout=300) as r:
                    text = r.read().decode("utf-8")
                if "OBS_VALUE" not in text[:5000]:
                    raise ValueError(f"no OBS_VALUE column; response starts: {text[:200]!r}")
                target.write_text(text, encoding="utf-8")
                print(f"[ok]   {name}  ({len(text) / 1e6:.1f} MB)  <- {url}")
                break
            except (urllib.error.URLError, ValueError, TimeoutError) as e:
                print(f"[fail] {url}\n       {e}")
        else:
            sys.exit(f"Could not download {name}. Download it in the browser into raw/ (see README).")


def _check_unique(df: pd.DataFrame, keys: list[str], file: str) -> None:
    dup = df.duplicated(keys)
    if dup.any():
        sys.exit(f"{file}: {dup.sum()} rows share the same {keys} - the file holds more series than expected. "
                 f"Columns: {list(df.columns)}")


def read_eurostat(file: str, dims: list[str]) -> pd.DataFrame:
    df = pd.read_csv(RAW / file, low_memory=False)
    print(f"  {file}: {len(df):,} rows x {df.shape[1]} columns")
    df = df.rename(columns={"TIME_PERIOD": "year", "OBS_VALUE": "value"})
    df["year"] = df["year"].astype(str).str[:4].astype(int)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df[dims + ["year", "value"] + [c for c in df.columns if c not in dims + ["year", "value"]]]


def read_ecb_monthly(file: str) -> pd.DataFrame:
    df = pd.read_csv(RAW / file, low_memory=False)
    print(f"  {file}: {len(df):,} rows x {df.shape[1]} columns")
    df = pd.DataFrame({"geo": df["REF_AREA"].replace(ECB_TO_EUROSTAT_GEO),
                       "period": df["TIME_PERIOD"].astype(str),
                       "value": pd.to_numeric(df["OBS_VALUE"], errors="coerce")}).dropna()
    _check_unique(df, ["geo", "period"], file)
    df["year"] = df["period"].str[:4].astype(int)
    g = df.groupby(["geo", "year"])["value"]
    out = g.mean().where(g.count() >= 9).dropna()
    return out.reset_index()


def read_income() -> pd.DataFrame:
    file = "eurostat_ilc_di03.csv"
    df = read_eurostat(file, ["geo", "age", "sex"])
    ind_col = next((c for c in df.columns if c.lower() in ("statinfo", "indic_il")), None)
    if ind_col is None:
        sys.exit(f"{file}: no statinfo/indic_il column. Columns: {list(df.columns)}")
    codes = df[ind_col].astype(str).unique().tolist()
    print(f"    {ind_col} codes in file: {codes}")

    frames = []
    for col, (prefer, contains) in INCOME_CODES.items():
        code = next((p for p in prefer if p in codes), None)
        if code is None:
            hits = [c for c in codes if contains in c.upper()]
            code = hits[0] if len(hits) == 1 else None
        if code is None:
            if col == "median_income_eur":
                sys.exit(f"{file}: can't tell which {ind_col} code is the median. Codes: {codes}")
            print(f"    no code found for {col}; column left empty")
            continue
        print(f"    {col}: using {ind_col} = {code}")
        part = df[df[ind_col].astype(str) == code]
        _check_unique(part, ["geo", "age", "sex", "year"], file)
        frames.append(part.set_index(["geo", "age", "sex", "year"])["value"].rename(col))
    return pd.concat(frames, axis=1).reset_index()


def age_label(code: str) -> str:
    if code == "TOTAL":
        return "All ages"
    if m := re.fullmatch(r"Y_LT(\d+)", code):
        return f"under {m[1]}"
    if m := re.fullmatch(r"Y_GE(\d+)", code):
        return f"{m[1]}+"
    if m := re.fullmatch(r"Y(\d+)-(\d+)", code):
        return f"{m[1]}-{m[2]}"
    return code


def rebase(df: pd.DataFrame, col: str, keys: list[str], base_year: int) -> pd.Series:
    base = (df.loc[df["year"] == base_year, keys + [col]]
              .drop_duplicates(keys).rename(columns={col: "_base"}))
    b = df[keys].merge(base, on=keys, how="left")["_base"].values
    return pd.Series(df[col].values / b * 100, index=df.index)


def yoy(df: pd.DataFrame, col: str, keys: list[str], pct: bool = True) -> pd.Series:
    prev = df[keys + ["year", col]].assign(year=df["year"] + 1).rename(columns={col: "_prev"})
    p = df[keys + ["year"]].merge(prev, on=keys + ["year"], how="left")["_prev"].values
    return pd.Series((df[col].values / p - 1) * 100 if pct else df[col].values - p, index=df.index)


def merge(start: int, end: int, base_year: int) -> pd.DataFrame:
    hpi = read_eurostat("eurostat_prc_hpi_a.csv", ["geo"])
    _check_unique(hpi, ["geo", "year"], "eurostat_prc_hpi_a.csv")
    hpi = hpi[["geo", "year", "value"]].rename(columns={"value": "house_price_index"})
    income = read_income()
    mortgage = read_ecb_monthly("ecb_mir_house_purchase.csv").rename(columns={"value": "mortgage_rate_pct"})
    hicp = read_ecb_monthly("ecb_icp_hicp.csv").rename(columns={"value": "hicp_index"})

    df = (income.merge(hpi, on=["geo", "year"], how="left")
                .merge(hicp, on=["geo", "year"], how="left")
                .merge(mortgage, on=["geo", "year"], how="left"))
    df = df[df["geo"].isin(COUNTRIES) & df["year"].between(start, end)].copy()
    df = df.sort_values(["geo", "age", "sex", "year"]).reset_index(drop=True)

    grp, ctry = ["geo", "age", "sex"], ["geo"]
    df["house_price_growth_pct"] = yoy(df, "house_price_index", grp)
    df["income_growth_pct"] = yoy(df, "median_income_eur", grp)
    df["inflation_pct"] = yoy(df, "hicp_index", grp)

    cpi = rebase(df, "hicp_index", ctry, base_year)
    price = rebase(df, "house_price_index", ctry, base_year)
    income_idx = rebase(df, "median_income_eur", grp, base_year)
    df["real_house_price_index"] = price / cpi * 100
    df["real_income_index"] = income_idx / cpi * 100
    df["price_to_income_index"] = price / income_idx * 100

    r = df["mortgage_rate_pct"] / 100 / 12
    df["_burden"] = df["house_price_index"] * (r / (1 - (1 + r) ** -(LOAN_YEARS * 12))) / df["median_income_eur"]
    df["mortgage_payment_to_income_index"] = rebase(df, "_burden", grp, base_year)
    change = yoy(df, "mortgage_payment_to_income_index", grp, pct=False)
    df["affordability_vs_prev_year"] = change.map(
        lambda x: None if pd.isna(x) else ("less affordable" if x > 0 else "more affordable"))

    info = df["geo"].map(COUNTRIES)
    df.insert(1, "country", info.str[0])
    df.insert(2, "region", info.str[1])
    adopted = info.str[2]
    df.insert(3, "euro_area", (adopted.notna() & (df["year"] >= adopted.fillna(9999))).map({True: "yes", False: "no"}))
    df.insert(5, "age_group", df.pop("age").map(age_label))
    sex = df.pop("sex")
    df.insert(6, "sex", sex.map({"T": "Total", "M": "Male", "F": "Female"}).fillna(sex))
    df = df.rename(columns={"geo": "country_code"}).drop(columns="_burden")
    first = ["country_code", "country", "region", "euro_area", "year", "age_group", "sex"]
    return df[first + [c for c in df.columns if c not in first]].round(3)


DICTIONARY = [
    ("country_code", "categorical (nominal)", "-", "Eurostat country code"),
    ("country", "categorical (nominal)", "-", "Country name"),
    ("region", "categorical (nominal)", "-", "European region: Northern, Western, Southern, Eastern"),
    ("euro_area", "categorical (binary)", "yes/no", "Country used the euro in that year"),
    ("year", "ordinal / temporal", "year", "Calendar year (income: EU-SILC survey year)"),
    ("age_group", "categorical (ordinal); groups overlap", "-", "Age group of the person (Eurostat ilc_di03)"),
    ("sex", "categorical (nominal)", "-", "Total, Male, Female"),
    ("median_income_eur", "quantitative (ratio)", "EUR / year", "Median equivalised net income, Eurostat ilc_di03"),
    ("mean_income_eur", "quantitative (ratio)", "EUR / year", "Mean equivalised net income, Eurostat ilc_di03"),
    ("house_price_index", "quantitative (interval)", "index, 2015=100", "House price index, all dwellings, Eurostat prc_hpi_a"),
    ("hicp_index", "quantitative (interval)", "index, 2015=100", "Consumer prices, annual average, ECB ICP"),
    ("mortgage_rate_pct", "quantitative (ratio)", "% p.a.", "Rate on new house-purchase loans, annual average, ECB MIR (euro-area countries)"),
    ("house_price_growth_pct", "quantitative", "%", "House price change vs previous year"),
    ("income_growth_pct", "quantitative", "%", "Median income change vs previous year"),
    ("inflation_pct", "quantitative", "%", "HICP change vs previous year"),
    ("real_house_price_index", "quantitative", "index, base year=100", "House prices deflated by HICP"),
    ("real_income_index", "quantitative", "index, base year=100", "Median income deflated by HICP"),
    ("price_to_income_index", "quantitative", "index, base year=100", "House prices relative to median income; >100 = less affordable than base year"),
    ("mortgage_payment_to_income_index", "quantitative", "index, base year=100",
     f"Monthly payment on a {LOAN_YEARS}-year loan for the same home relative to median income; >100 = harder to finance"),
    ("affordability_vs_prev_year", "categorical (binary)", "-", "Payment-to-income index rose (less affordable) or fell (more affordable)"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-download the raw files")
    ap.add_argument("--start", type=int, default=2010)
    ap.add_argument("--end", type=int, default=2025)
    ap.add_argument("--base-year", type=int, default=2015)
    args = ap.parse_args()

    print("Step 1: download")
    download(args.refresh)
    print("\nStep 2: merge")
    df = merge(args.start, args.end, args.base_year)

    out = HERE / "housing_affordability_panel.csv"
    df.to_csv(out, index=False)
    pd.DataFrame(DICTIONARY, columns=["variable", "type", "unit", "description"]).to_csv(
        HERE / "data_dictionary.csv", index=False)

    print(f"\nWrote {out.name}: {len(df):,} rows x {df.shape[1]} columns "
          f"({'meets' if len(df) >= 10_000 and df.shape[1] >= 10 else 'BELOW'} the 10,000 x 10 minimum)")
    print(f"  countries {df['country_code'].nunique()}, years {df['year'].min()}-{df['year'].max()}, "
          f"age groups {df['age_group'].nunique()}, sexes {df['sex'].nunique()}")
    print("\nMissing values (% of rows):")
    print((df.isna().mean() * 100).round(1).loc[lambda s: s > 0].to_string())


if __name__ == "__main__":
    main()
