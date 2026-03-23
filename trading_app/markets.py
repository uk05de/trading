"""DAX, TecDAX, MDAX, Dow Jones, Nasdaq 100 tickers + Sparten-Zuordnung."""

from __future__ import annotations

# ===========================================================================
# DEV-Modus: Nur 2 Aktien pro Sektor aktiv (für schnellere Scans).
# Zum Reaktivieren: Kommentarzeichen "# DEV " am Zeilenanfang entfernen.
# ===========================================================================

# ---------------------------------------------------------------------------
# Deutsche Indizes
# ---------------------------------------------------------------------------
INDICES: dict[str, str] = {
    "^GDAXI": "DAX 40",
    "^TECDAX": "TecDAX",
    "^MDAXI": "MDAX",
    "^DJI": "Dow Jones",
    "^NDX": "Nasdaq 100",
}

# ---------------------------------------------------------------------------
# DAX 40 Einzelwerte
# ---------------------------------------------------------------------------
DAX_COMPONENTS: dict[str, str] = {
    # --- Technology (2) ---
    "SAP.DE": "SAP",
    "IFX.DE": "Infineon",
    # --- Industrials (8) ---
    "SIE.DE": "Siemens",
    "AIR.DE": "Airbus",
    "ENR.DE": "Siemens Energy",
    "RHM.DE": "Rheinmetall",
    "DHL.DE": "DHL Group",
    "DTG.DE": "Daimler Truck",
    "MTX.DE": "MTU Aero Engines",
    "G1A.DE": "GEA Group",
    # --- Financial Services (6) ---
    "ALV.DE": "Allianz",
    "DBK.DE": "Deutsche Bank",
    "MUV2.DE": "Munich Re",
    "DB1.DE": "Deutsche Börse",
    "CBK.DE": "Commerzbank",
    "HNR1.DE": "Hannover Rück",
    # --- Consumer Cyclical (7) ---
    "MBG.DE": "Mercedes-Benz",
    "BMW.DE": "BMW",
    "VOW3.DE": "Volkswagen",
    "ADS.DE": "Adidas",
    "CON.DE": "Continental",
    "PAH3.DE": "Porsche SE",
    "ZAL.DE": "Zalando",
    # --- Healthcare (6) ---
    "MRK.DE": "Merck KGaA",
    "SHL.DE": "Siemens Healthineers",
    "BAYN.DE": "Bayer",
    "FRE.DE": "Fresenius",
    "FME.DE": "Fresenius Med. Care",
    "QIA.DE": "Qiagen",
    # --- Communication Services (1) ---
    "DTE.DE": "Deutsche Telekom",
    # --- Utilities (2) ---
    "EOAN.DE": "E.ON",
    "RWE.DE": "RWE",
    # --- Basic Materials (5) ---
    "BAS.DE": "BASF",
    "HEI.DE": "Heidelberg Materials",
    "SY1.DE": "Symrise",
    "BNR.DE": "Brenntag",
    "1COV.F": "Covestro",
    # --- Consumer Defensive (2) ---
    "HEN3.DE": "Henkel",
    "BEI.DE": "Beiersdorf",
    # --- Real Estate (1) ---
    "VNA.DE": "Vonovia",
}

# ---------------------------------------------------------------------------
# TecDAX Einzelwerte (ohne DAX-Überschneidungen)
# ---------------------------------------------------------------------------
TECDAX_COMPONENTS: dict[str, str] = {
    # --- Technology (14) ---
    "NEM.DE": "Nemetschek",
    "AIXA.DE": "Aixtron",
    "BC8.DE": "Bechtle",
    "IOS.DE": "IONOS",
    "ELG.DE": "Elmos Semiconductor",
    "JEN.DE": "Jenoptik",
    "AOF.DE": "ATOSS Software",
    "KTN.DE": "Kontron",
    "S92.DE": "SMA Solar",
    "SMHN.DE": "SÜSS MicroTec",
    "TMV.DE": "TeamViewer",
    "COK.DE": "CANCOM",
    "WAF.DE": "Siltronic",
    "NA9.DE": "Nagarro",
    # --- Healthcare (6) ---
    "SRT3.DE": "Sartorius",
    "AFX.DE": "Carl Zeiss Meditec",
    "OBCK.DE": "Ottobock",
    "DRW3.DE": "Drägerwerk",
    "EUZ.DE": "Eckert & Ziegler",
    "EVT.DE": "Evotec",
    # --- Industrials (1) ---
    "NDX1.DE": "Nordex",
    # --- Communication Services (3) ---
    "UTDI.DE": "United Internet",
    "FNTN.DE": "freenet",
    "1U1.DE": "1&1",
}

# ---------------------------------------------------------------------------
# MDAX Einzelwerte (ohne DAX- und TecDAX-Überschneidungen)
# ---------------------------------------------------------------------------
MDAX_COMPONENTS: dict[str, str] = {
    # --- Consumer Cyclical (10) ---
    "P911.DE": "Porsche AG",
    "KBX.DE": "Knorr-Bremse",
    "HLE.DE": "Hella",
    "SHA0.DE": "Schaeffler",
    "DHER.DE": "Delivery Hero",
    "AMV0.DE": "Aumovio",
    "AG1.DE": "AUTO1 Group",
    "TUI1.DE": "TUI",
    "PUM.DE": "Puma",
    "BOSS.DE": "Hugo Boss",
    # --- Financial Services (3) ---
    "TLX.DE": "Talanx",
    "DWS.DE": "DWS Group",
    "FTK.DE": "flatexDEGIRO",
    # --- Industrials (14) ---
    "HOT.DE": "HOCHTIEF",
    "LHA.DE": "Lufthansa",
    "8TRA.DE": "Traton",
    "HAG.DE": "Hensoldt",
    "NDA.DE": "Aurubis",
    "RAA.DE": "Rational",
    "FRA.DE": "Fraport",
    "KGX.DE": "Kion Group",
    "TKMS.DE": "TKMS",
    "TKA.DE": "thyssenkrupp",
    "GBF.DE": "Bilfinger",
    "KRN.DE": "Krones",
    "R3NK.DE": "RENK Group",
    "JUN3.DE": "Jungheinrich",
    # --- Communication Services (3) ---
    "EVD.DE": "CTS Eventim",
    "RRTL.DE": "RTL Group",
    "SAX.DE": "Ströer",
    # --- Basic Materials (5) ---
    "EVK.DE": "Evonik",
    "FPE3.DE": "Fuchs",
    "WCH.DE": "Wacker Chemie",
    "SDF.DE": "K+S",
    "LXS.DE": "Lanxess",
    # --- Real Estate (3) ---
    "LEG.DE": "LEG Immobilien",
    "TEG.DE": "TAG Immobilien",
    "AT1.DE": "Aroundtown",
    # --- Healthcare (2) ---
    "FIE.DE": "Fielmann",
    "RDC.DE": "Redcare Pharmacy",
}

# ---------------------------------------------------------------------------
# Dow Jones 30
# ---------------------------------------------------------------------------
DOW_COMPONENTS: dict[str, str] = {
    # US-Titel deaktiviert – System ist auf DE-Markt kalibriert.
    # Brauchen eigenen Markt-Kontext (S&P statt DAX) und eigene Veto-Regeln.
    # --- Financial Services (5) ---
    # DEV "GS": "Goldman Sachs",
    # DEV "V": "Visa",
    # DEV "AXP": "American Express",
    # DEV "TRV": "Travelers Companies",
    # DEV "JPM": "JPMorgan Chase",
    # --- Industrials (4) ---
    # DEV "CAT": "Caterpillar",
    # DEV "HON": "Honeywell",
    # DEV "BA": "Boeing",
    # DEV "MMM": "3M",
    # --- Technology (6) ---
    # DEV "MSFT": "Microsoft",
    # DEV "NVDA": "Nvidia",
    # DEV "AAPL": "Apple",
    # DEV "IBM": "IBM",
    # DEV "CRM": "Salesforce",
    # DEV "CSCO": "Cisco Systems",
    # --- Healthcare (4) ---
    # DEV "AMGN": "Amgen",
    # DEV "UNH": "UnitedHealth Group",
    # DEV "JNJ": "Johnson & Johnson",
    # DEV "MRK": "Merck & Co.",
    # --- Consumer Cyclical (4) ---
    # DEV "HD": "Home Depot",
    # DEV "AMZN": "Amazon",
    # DEV "MCD": "McDonald's",
    # DEV "NKE": "Nike",
    # --- Basic Materials (1) ---
    # DEV "SHW": "Sherwin-Williams",
    # --- Consumer Defensive (3) ---
    # DEV "WMT": "Walmart",
    # DEV "PG": "Procter & Gamble",
    # DEV "KO": "Coca-Cola",
    # --- Communication Services (2) ---
    # DEV "VZ": "Verizon",
    # DEV "DIS": "Walt Disney",
    # --- Energy (1) ---
    # DEV "CVX": "Chevron",
}

# ---------------------------------------------------------------------------
# Nasdaq 100 (ohne Dow-Überschneidungen)
# ---------------------------------------------------------------------------
NASDAQ_COMPONENTS: dict[str, str] = {
    # US-Titel deaktiviert – siehe DOW_COMPONENTS Kommentar.
    # --- Communication Services (10) ---
    # DEV "GOOGL": "Alphabet",
    # DEV "META": "Meta Platforms",
    # DEV "NFLX": "Netflix",
    # DEV "TMUS": "T-Mobile US",
    # DEV "APP": "AppLovin",
    # DEV "CMCSA": "Comcast",
    # DEV "WBD": "Warner Bros. Discovery",
    # DEV "EA": "Electronic Arts",
    # DEV "CHTR": "Charter Communications",
    # DEV "TTWO": "Take-Two Interactive",
    # --- Technology (37) ---
    # DEV "AVGO": "Broadcom",
    # DEV "ASML": "ASML Holding",
    # DEV "MU": "Micron Technology",
    # DEV "PLTR": "Palantir Technologies",
    # DEV "AMD": "Advanced Micro Devices",
    # DEV "AMAT": "Applied Materials",
    # DEV "LRCX": "Lam Research",
    # DEV "INTC": "Intel",
    # DEV "KLAC": "KLA Corporation",
    # DEV "TXN": "Texas Instruments",
    # DEV "SHOP": "Shopify",
    # DEV "QCOM": "Qualcomm",
    # DEV "ARM": "Arm Holdings",
    # DEV "ADI": "Analog Devices",
    # DEV "INTU": "Intuit",
    # DEV "CRWD": "CrowdStrike",
    # DEV "ADBE": "Adobe",
    # DEV "PANW": "Palo Alto Networks",
    # DEV "WDC": "Western Digital",
    # DEV "STX": "Seagate Technology",
    # DEV "ADP": "Automatic Data Processing",
    # DEV "SNPS": "Synopsys",
    # DEV "CDNS": "Cadence Design Systems",
    # DEV "MRVL": "Marvell Technology",
    # DEV "FTNT": "Fortinet",
    # DEV "ADSK": "Autodesk",
    # DEV "MPWR": "Monolithic Power Systems",
    # DEV "NXPI": "NXP Semiconductors",
    # DEV "MSTR": "MicroStrategy",
    # DEV "DDOG": "Datadog",
    # DEV "WDAY": "Workday",
    # DEV "PAYX": "Paychex",
    # DEV "MCHP": "Microchip Technology",
    # DEV "ROP": "Roper Technologies",
    # DEV "CTSH": "Cognizant",
    # DEV "ZS": "Zscaler",
    # DEV "TEAM": "Atlassian",
    # --- Consumer Cyclical (10) ---
    # DEV "TSLA": "Tesla",
    # DEV "BKNG": "Booking Holdings",
    # DEV "PDD": "PDD Holdings",
    # DEV "SBUX": "Starbucks",
    # DEV "MELI": "MercadoLibre",
    # DEV "MAR": "Marriott International",
    # DEV "ORLY": "O'Reilly Automotive",
    # DEV "DASH": "DoorDash",
    # DEV "ROST": "Ross Stores",
    # DEV "ABNB": "Airbnb",
    # --- Consumer Defensive (7) ---
    # DEV "COST": "Costco",
    # DEV "PEP": "PepsiCo",
    # DEV "MNST": "Monster Beverage",
    # DEV "MDLZ": "Mondelez International",
    # DEV "CCEP": "Coca-Cola Europacific Partners",
    # DEV "KDP": "Keurig Dr Pepper",
    # DEV "KHC": "Kraft Heinz",
    # --- Healthcare (9) ---
    # DEV "GILD": "Gilead Sciences",
    # DEV "ISRG": "Intuitive Surgical",
    # DEV "VRTX": "Vertex Pharmaceuticals",
    # DEV "REGN": "Regeneron Pharmaceuticals",
    # DEV "IDXX": "Idexx Laboratories",
    # DEV "ALNY": "Alnylam Pharmaceuticals",
    # DEV "INSM": "Insmed",
    # DEV "DXCM": "DexCom",
    # DEV "GEHC": "GE HealthCare",
    # --- Basic Materials (1) ---
    # DEV "LIN": "Linde",
    # --- Utilities (4) ---
    # DEV "CEG": "Constellation Energy",
    # DEV "AEP": "American Electric Power",
    # DEV "XEL": "Xcel Energy",
    # DEV "EXC": "Exelon",
    # --- Energy (2) ---
    # DEV "BKR": "Baker Hughes",
    # DEV "FANG": "Diamondback Energy",
    # --- Industrials (10) ---
    # DEV "CSX": "CSX Corporation",
    # DEV "CTAS": "Cintas",
    # DEV "FAST": "Fastenal",
    # DEV "PCAR": "Paccar",
    # DEV "FER": "Ferrovial",
    # DEV "AXON": "Axon Enterprise",
    # DEV "TRI": "Thomson Reuters",
    # DEV "ODFL": "Old Dominion Freight Line",
    # DEV "CPRT": "Copart",
    # DEV "VRSK": "Verisk Analytics",
    # --- Financial Services (1) ---
    # DEV "PYPL": "PayPal",
    # --- Real Estate (1) ---
    # DEV "CSGP": "CoStar Group",
}

# ---------------------------------------------------------------------------
# Sparten-Zuordnung (Ticker → Sektor)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# GICS-Sektoren (von Yahoo Finance, gecacht in data/gics_sectors.json)
# ---------------------------------------------------------------------------
import json as _json
from pathlib import Path as _Path

# GICS Englisch → Deutsche Anzeigenamen
_GICS_DE = {
    "Technology": "Technology",
    "Healthcare": "Healthcare",
    "Financial Services": "Financial Services",
    "Consumer Cyclical": "Consumer Cyclical",
    "Consumer Defensive": "Consumer Defensive",
    "Industrials": "Industrials",
    "Energy": "Energy",
    "Basic Materials": "Basic Materials",
    "Communication Services": "Communication Services",
    "Real Estate": "Real Estate",
    "Utilities": "Utilities",
}

def _load_gics_sectors() -> dict[str, str]:
    """Load GICS sectors from cache file."""
    cache = _Path(__file__).parent / "data" / "gics_sectors.json"
    if cache.exists():
        raw = _json.loads(cache.read_text())
        return {t: _GICS_DE.get(s, s) for t, s in raw.items() if s}
    return {}

_gics_cache = _load_gics_sectors()

# Indizes bekommen spezielle Sektor-Labels
_INDEX_SECTORS = {
    "^GDAXI": "Index: DAX",
    "^TECDAX": "Index: TecDAX",
    "^MDAXI": "Index: MDAX",
    "^DJI": "Index: Dow Jones",
    "^NDX": "Index: Nasdaq 100",
}

# Alle Sektoren (ohne Indizes) – dynamisch aus den GICS-Daten
SECTORS: list[str] = sorted(set(_gics_cache.values())) if _gics_cache else [
    "Technology", "Healthcare", "Financial Services", "Consumer Cyclical",
    "Consumer Defensive", "Industrials", "Energy", "Basic Materials",
    "Communication Services", "Real Estate", "Utilities",
]

# SECTOR_MAP: Ticker → Sektorname (für sectors.py und analyzer.py)
SECTOR_MAP: dict[str, str] = {**_INDEX_SECTORS, **_gics_cache}


def get_sector(ticker: str) -> str:
    """Return sector for a ticker, or 'Sonstige' if unknown."""
    return SECTOR_MAP.get(ticker, "Sonstige")


def get_index(ticker: str) -> str:
    """Return the index a ticker belongs to."""
    if ticker in INDICES:
        return INDICES[ticker]
    if ticker in DAX_COMPONENTS:
        return "DAX"
    if ticker in TECDAX_COMPONENTS:
        return "TecDAX"
    if ticker in MDAX_COMPONENTS:
        return "MDAX"
    if ticker in DOW_COMPONENTS:
        return "Dow"
    if ticker in NASDAQ_COMPONENTS:
        return "Nasdaq"
    return "–"
