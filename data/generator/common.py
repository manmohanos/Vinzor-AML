"""Shared utilities: deterministic RNG, ID factory, and small helpers.

The entire synthetic dataset is generated from a FIXED seed so that every run
produces byte-identical output. Determinism is a hard requirement: the prototype
replays the same events, opens the same cases, and produces the same audit trail on
every run, which is exactly the "decision is reproducible" property the curriculum
demands. Do not remove the fixed seed.
"""

from __future__ import annotations

import hashlib
import random

# --------------------------------------------------------------------------- #
# Fixed seed (do not change — changing it silently breaks schema.md and tests) #
# --------------------------------------------------------------------------- #
SEED = 20260807

_rng = random.Random(SEED)


def rng() -> random.Random:
    """Return the shared seeded RNG instance."""
    return _rng


# --------------------------------------------------------------------------- #
# ID factory                                                                    #
# --------------------------------------------------------------------------- #
class IdFactory:
    """Unique, greppable, stable IDs like ``per_0001``.

    A fresh factory is created per entity table so each type has its own prefix and
    its own running counter.
    """

    def __init__(self, prefix: str, width: int = 4, start: int = 1) -> None:
        self.prefix = prefix
        self.width = width
        self._n = start

    def next(self) -> str:
        s = f"{self.prefix}_{self._n:0{self.width}d}"
        self._n += 1
        return s

    def seq(self, count: int) -> list[str]:
        return [self.next() for _ in range(count)]


# --------------------------------------------------------------------------- #
# Name / value factories (clearly synthetic)                                   #
# --------------------------------------------------------------------------- #
FIRST = [
    "Aarav", "Mira", "Kavya", "Rohan", "Ishaan", "Ananya", "Vihaan", "Saanvi",
    "Arjun", "Diya", "Kabir", "Meera", "Advait", "Naina", "Reyansh", "Tara",
    "Yash", "Zoya", "Dev", "Aisha", "Nikhil", "Priya", "Siddharth", "Lakshmi",
    "Varun", "Anika", "Karan", "Ritika", "Manish", "Sneha", "Raj", "Pooja",
    "John", "Emily", "Michael", "Sarah", "David", "Olivia", "Daniel", "Sophia",
    "Wei", "Mei", "Chen", "Zhang", "Hiro", "Yuki", "Sofia", "Lucas",
    "Ahmed", "Fatima", "Omar", "Layla", "Diego", "Camila", "Hannah", "Ethan",
]

LAST = [
    "Sharma", "Verma", "Patel", "Gupta", "Mehta", "Singh", "Kumar", "Iyer",
    "Nair", "Reddy", "Rao", "Joshi", "Desai", "Chatterjee", "Banerjee",
    "Malhotra", "Kapoor", "Agarwal", "Ghosh", "Das", "Chopra", "Bhatia",
    "Khan", "Hussain", "Ali", "Chen", "Wang", "Li", "Tanaka", "Sato",
    "Smith", "Johnson", "Brown", "Williams", "Garcia", "Martinez", "Wilson",
    "Anderson", "Thomas", "Jackson", "Miller", "Davis", "Moore", "White",
]

COMPANY_WORD = [
    "Meridian", "Atlas", "Orion", "Vertex", "Apex", "Zenith", "Quantum",
    "Nimbus", "Solstice", "Pinnacle", "Lumina", "Crest", "Harbor", "Vantage",
    "Summit", "Beacon", "Clarity", "Cascade", "Dynamic", "Everest",
]

COMPANY_SUFFIX = [
    "Holdings", "Capital", "Investments", "Ventures", "Advisors", "Partners",
    "Trading", "Enterprises", "Group", "International", "Private Limited",
    "Limited", "Luxembourg S.à r.l.", "B.V.", "Pte. Ltd.", "Limited",
]

TRUST_NAME = [
    "Krishna Family Trust", "Meridian Growth Trust", "Anand Discretionary Trust",
    "Sovereign Succession Trust", "Harbor Beneficiary Trust", "Crest Settlor Trust",
]

FUND_TYPE = ["AIF", "PE", "VC", "Hedge", "Private Credit", "Infrastructure"]
STRATEGY = [
    "Early-stage venture", "Growth equity", "Buyout", "Venture debt",
    "Distressed", "Infrastructure", "Real estate", "Secondary",
]

CURRENCIES = ["USD", "USD", "USD", "USD", "EUR", "GBP", "SGD", "AED", "INR", "JPY"]

BANKS = [
    "HSBC Singapore", "DBS Bank", "UBS Zurich", "Standard Chartered Dubai",
    "ICICI Bank", "HDFC Bank", "Citi Mumbai", "JP Morgan London", "BNP Paris",
    "Deutsche Frankfurt", "Bank of America NY", "Maybank Malaysia", "OCBC Singapore",
]

JURISDICTIONS_HIGH_RISK = ["IR", "KP", "SY", "SD", "CU", "MM"]
JURISDICTIONS_STANDARD = [
    "SG", "US", "GB", "DE", "FR", "NL", "LU", "MU", "AE", "IN", "JP", "SG", "CA",
]
COUNTRY_NAMES = {
    "SG": "Singapore", "US": "United States", "GB": "United Kingdom",
    "DE": "Germany", "FR": "France", "NL": "Netherlands", "LU": "Luxembourg",
    "MU": "Mauritius", "AE": "United Arab Emirates", "IN": "India",
    "JP": "Japan", "CA": "Canada", "IR": "Iran", "KP": "North Korea",
    "SY": "Syria", "SD": "Sudan", "CU": "Cuba", "MM": "Myanmar",
}

INDUSTRIES = [
    "Financial services", "Technology", "Healthcare", "Real estate",
    "Infrastructure", "Consumer", "Energy", "Manufacturing", "Telecom",
    "Pharmaceuticals",
]

DOC_TYPES = [
    "PASSPORT", "PAN", "CERTIFICATE_OF_INCORPORATION", "TRUST_DEED",
    "KYC_FORM", "TIN", "ADDRESS_PROOF", "BOARD_RESOLUTION",
]

PEP_ROLES = [
    "Head of state", "Minister of Finance", "Member of parliament",
    "Senior judge", "Senior military officer", "Central bank official",
    "State-owned enterprise executive",
]

ADVERSE_CATEGORIES = [
    "FRAUD", "MONEY_LAUNDERING", "CORRUPTION", "SANCTIONS",
    "INSIDER_TRADING", "TAX_EVASION",
]


def person_name(r: random.Random) -> str:
    return f"{r.choice(FIRST)} {r.choice(LAST)}"


def company_name(r: random.Random) -> str:
    return f"{r.choice(COMPANY_WORD)} {r.choice(COMPANY_WORD)} {r.choice(COMPANY_SUFFIX)}"


def _stable_digest(*parts: str, length: int = 8) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:length]


def manifest_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
