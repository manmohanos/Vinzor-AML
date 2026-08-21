"""Bringing a firm's own spreadsheets in, without guessing.

Until now the only data that could enter a workspace was the synthetic seed,
which makes a pilot impossible: the first thing a real firm has is a
spreadsheet, exported from Excel with whatever column names that firm
happens to use. Two kinds are read -- a sheet of parties (customers,
investors, account holders) and a sheet of payments (a statement export, a
settlement file) -- and the sheet itself says which it is, by the columns
it carries.

The whole design problem is that we do not know those names, and the wrong
answer is to guess. A column called "Country" might be nationality, residence,
or incorporation, and quietly picking one would put a fact on a compliance
record that nobody asserted. So:

* headers are matched against a fixed vocabulary of spellings we recognise;
* anything unrecognised is reported and left out, never approximated;
* anything ambiguous -- two columns claiming the same field -- refuses the
  import outright rather than choosing;
* nothing is written until the reader has seen the mapping and passed
  ``--confirm``. A dry run is the default because an append-only log has no
  undo, and an import that lands wrong is permanent.

Rows become ordinary ``ENTITY_REGISTERED`` and ``COMMITMENT_MADE`` events
through ``engine.ingest``. There is no import-shaped side door into the log.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date as _date_type
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from . import xlsx
from .countries import COUNTRIES
from .model import EntityKind, EventType

#: Header spellings we accept for each field. Matching is done on a normalised
#: form (lowercased, non-letters stripped), so "Date of Birth", "date_of_birth"
#: and "DOB" all land on the same entry. Only what is listed here is
#: recognised; a column we cannot name is reported, not approximated.
FIELDS: Mapping[str, tuple[str, ...]] = {
    "name": ("name", "fullname", "legalname", "investorname", "partyname",
             "entityname", "clientname", "lpname", "trustname",
             "nameofinvestor", "applicantname", "customername", "custname",
             "accountname", "acctname", "holdername", "firstholdername",
             "primaryholdername"),
    # Clause 5.4.2(a)(i) asks for a full name "including any aliases", and
    # until 20 August 2026 there was nowhere on a party record to put one.
    # Two blocks had already found the hole from the other end: screening
    # could only ever ask a watchlist about the one name on the record,
    # and the readiness check had to declare the aliases limb unmeasured
    # because nothing could hold an answer. A maiden name, a name before
    # naturalisation and a name in another script are all ordinary, and a
    # sanctions list carries them as a matter of course.
    "alias": ("alias", "aliases", "aka", "alsoknownas", "othername",
              "othernames", "formername", "formernames", "maidenname",
              "previousname", "previousnames", "tradingname", "tradingas",
              "doingbusinessas", "dba", "alternatename", "nameinlocalscript"),
    # Registrar and KYC exports split the name; the pieces are joined back
    # into the one name a watchlist knows.
    "first_name": ("firstname", "fname", "givenname",
                   "primaryholderfirstname"),
    "middle_name": ("middlename", "mname", "primaryholdermiddlename"),
    "last_name": ("lastname", "lname", "surname", "primaryholderlastname"),
    "kind": ("kind", "type", "entitytype", "partytype", "investortype",
             "customertype", "clienttype", "constitution", "consttype",
             "constitutiontype", "investorcategory", "custtype"),
    "nationality": ("nationality", "citizenship", "countryofcitizenship"),
    "country_of_residence": ("countryofresidence", "residence", "resident",
                             "residencecountry", "countryresident",
                             "countryoftaxresidency", "taxresidency",
                             "taxresidencycountry", "countryofdomicile"),
    "country_of_incorporation": ("countryofincorporation", "incorporatedin",
                                 "incorporation", "incorporationcountry",
                                 "placeofincorporation",
                                 "countryofregistration",
                                 "jurisdictionofincorporation"),
    "jurisdiction": ("jurisdiction", "registeredin", "domicile"),
    "dob": ("dob", "dateofbirth", "birthdate", "born", "dobdt",
            "primaryholderdob"),
    "date_of_incorporation": ("dateofincorporation", "dateofincorp", "doi",
                              "incorporationdate", "incorpdate",
                              "incorporationdt", "registrationdate",
                              "regdate", "dateofregistration"),
    "id_document_type": ("iddocumenttype", "documenttype", "idtype",
                         "identificationtype", "idprooftype",
                         "proofofidentity", "kycdoctype"),
    "id_document_number": ("iddocumentnumber", "documentnumber", "idnumber",
                           "passportnumber", "passport", "identitynumber",
                           "identificationnumber", "idproofno",
                           "nationalid", "docno"),
    # Indian identifiers, each its own fact. PAN doubles as the sturdiest
    # dedupe key a sheet can carry.
    "pan": ("pan", "panno", "pannumber", "pancardno", "pancard",
            "primaryholderpan"),
    "cin": ("cin", "cinno", "cinnumber", "corporateidentitynumber",
            "llpin", "companyregno"),
    "lei": ("lei", "leino", "leicode", "leinumber",
            "legalentityidentifier"),
    # Clause 5.4.2 requires an address and contact details for every
    # customer, and the importer could not accept either -- so a sheet that
    # carried them threw them away and the party looked incomplete for a
    # reason of our own making.
    "address": ("address", "addressline", "addressline1", "address1",
                "residentialaddress", "registeredaddress",
                "permanentaddress", "correspondenceaddress",
                "streetaddress", "addr", "principalplaceofbusiness"),
    "address_line_2": ("addressline2", "address2"),
    "city": ("city", "town", "district"),
    "state": ("state", "province", "region"),
    "postal_code": ("postalcode", "pincode", "zip", "zipcode", "postcode"),
    "phone": ("phone", "mobile", "telephone", "contactnumber", "mobileno",
              "phoneno", "contactno", "mobilenumber", "cellphone",
              "phonenumber"),
    "email": ("email", "emailid", "emailaddress", "mailid"),
    "customer_reference": ("folio", "foliono", "folionumber", "customerid",
                           "custid", "cifnumber", "cifno", "clientid",
                           "clientcode", "accountno", "accountnumber",
                           "acno", "acctno", "unitholderid"),
    # A sheet that names an owner and a stake declares ownership; both
    # columns must be present for either to mean anything.
    "owner_name": ("ownername", "parentownername", "nameofubo", "uboname",
                   "beneficialownername", "nameofbeneficialowner",
                   "controllingpersonname", "nameofcontrollingperson",
                   "parentcompany", "holdingcompany", "holdingcompanyname",
                   "shareholdername", "nameofshareholder"),
    "owner_share": ("ownershippercentage", "ownership", "ownershippercent",
                    "percentageofholding", "percentageofshareholding",
                    "shareholding", "sharepercent", "stake",
                    "beneficialinterest", "holdingpercent"),
    "commitment_amount": ("commitment", "commitmentamount", "committed",
                          "commitmentusd", "amount", "subscription"),
    "commitment_currency": ("currency", "commitmentcurrency", "ccy"),
    "fund": ("fund", "fundname", "scheme", "schemename"),
}

#: What a payments sheet calls things. Drawn from what banks and payment
#: services actually export -- statement downloads with split debit and
#: credit columns, settlement files with one signed amount, SWIFT- and
#: ISO-derived exports with a direction letter -- rather than from what a
#: tidy schema would prefer they exported.
PAYMENT_FIELDS: Mapping[str, tuple[str, ...]] = {
    "payer": ("payer", "payername", "remitter", "remittername",
              "remittingparty", "sender", "sendername",
              "debtor", "debtorname", "orderingcustomer", "orderingparty",
              "payerremitter", "receivedfrom", "paidby"),
    # Who the money was *for*. Without this every imported payment is
    # recorded against the sender, payer and subject are the same party,
    # and no payment rule can fire on a file this importer read -- the one
    # rule left compares those two names, and two copies of one name are
    # never different. It was added for the counterparty rules, which
    # existed to notice one sender funding several investors and were
    # removed on 21 August 2026; it earns its place for a smaller reason
    # now, and still earns it. A fund administrator's payment file names
    # the investor; a raw bank statement often does too, in the beneficiary
    # column or the reference.
    "beneficiary": ("beneficiary", "beneficiaryname", "benename", "payee",
                    "payeename", "creditor", "creditorname", "receivername",
                    "recipientname", "investor", "investorname",
                    "onbehalfof", "forinvestor", "accountholdername",
                    "creditedto"),
    "amount": ("amount", "amt", "transactionamount", "txnamount",
               "tranamount", "amountinr", "grossamount", "gross",
               "settlementamount", "value", "paymentamount"),
    "debit_amount": ("debit", "debitamount", "debitamt", "debits",
                     "withdrawal", "withdrawalamt", "withdrawalamount",
                     "withdrawalamountinr", "withdrawals", "dramount",
                     "dramt", "paidout", "moneyout", "debitinr"),
    "credit_amount": ("credit", "creditamount", "creditamt", "credits",
                      "deposit", "depositamt", "depositamount",
                      "depositamountinr", "deposits", "cramount", "cramt",
                      "paidin", "moneyin", "creditinr"),
    "direction": ("crdr", "drcr", "dc", "cd", "dcmark", "debitcreditmark",
                  "debitcredit", "creditdebitindicator", "cdtdbtind",
                  "transactionnature"),
    "currency": ("currency", "ccy", "cur", "curr", "currencycode",
                 "txncurrency", "transactioncurrency"),
    "date": ("date", "txndate", "trandate", "transactiondate", "transdate",
             "postingdate", "postdate", "posteddate", "bookingdate",
             "bookdate", "entrydate", "datetime", "txnposteddate",
             "paymentdate"),
    "value_date": ("valuedate", "valuedt", "valdate", "valdt",
                   "effectivedate"),
    "reference": ("refno", "reference", "referenceno", "referencenumber",
                  "refnochequeno", "chqrefno", "chqno", "chequeno",
                  "chequenumber", "utr", "utrno", "utrnumber", "rrn",
                  "transactionrefno", "transactionreference",
                  "bankreference", "bankrefno", "endtoendid", "upirefno",
                  "transactionid", "txnid", "tranid", "paymentid",
                  "orderid"),
    "narration": ("narration", "description", "particulars",
                  "transactionparticulars", "transactionremarks", "remarks",
                  "transactiondetails", "details",
                  "transactiondescription", "txndetails", "narrative",
                  "memo", "paymentdetails", "remittanceinformation"),
}

#: What each recognised column stands for, in the words a reader would use.
#: Refusals name columns by meaning rather than by the key this file happens
#: to hash them under.
MEANINGS: Mapping[str, str] = {
    "name": "the party's name",
    "alias": "any other name this party is known by",
    "first_name": "the first part of the name",
    "middle_name": "the middle part of the name",
    "last_name": "the last part of the name",
    "kind": "what each party is",
    "nationality": "nationality",
    "country_of_residence": "country of residence",
    "country_of_incorporation": "country of incorporation",
    "jurisdiction": "jurisdiction",
    "dob": "date of birth",
    "date_of_incorporation": "date of incorporation",
    "id_document_type": "identity document type",
    "id_document_number": "identity document number",
    "pan": "PAN",
    "cin": "CIN",
    "lei": "LEI",
    "customer_reference": "your own reference for the party",
    "owner_name": "who owns the party",
    "owner_share": "the owner's share",
    "address": "the party's address",
    "address_line_2": "the second line of the address",
    "city": "the town or city",
    "state": "the state or province",
    "postal_code": "the postal code",
    "phone": "a telephone number",
    "email": "an email address",
    "commitment_amount": "the amount committed",
    "commitment_currency": "the commitment's currency",
    "fund": "the fund committed to",
    "payer": "who each payment came from",
    "beneficiary": "who each payment was for",
    "amount": "the amount",
    "debit_amount": "money going out",
    "credit_amount": "money arriving",
    "direction": "whether money came in or went out",
    "currency": "the currency",
    "date": "each payment's date",
    "value_date": "the day the money took effect",
    "reference": "the bank's reference",
    "narration": "the bank's description",
}

#: Entity kinds, as a spreadsheet is likely to spell them.
KINDS: Mapping[str, EntityKind] = {
    "person": EntityKind.PERSON, "individual": EntityKind.PERSON,
    "natural person": EntityKind.PERSON, "natural": EntityKind.PERSON,
    "company": EntityKind.COMPANY, "corporate": EntityKind.COMPANY,
    "corporation": EntityKind.COMPANY, "body corporate": EntityKind.COMPANY,
    "ltd": EntityKind.COMPANY, "limited": EntityKind.COMPANY,
    "llc": EntityKind.COMPANY, "inc": EntityKind.COMPANY,
    "partnership": EntityKind.PARTNERSHIP, "llp": EntityKind.PARTNERSHIP,
    "firm": EntityKind.PARTNERSHIP,
    "trust": EntityKind.TRUST, "family trust": EntityKind.TRUST,
    "fund": EntityKind.FUND, "scheme": EntityKind.FUND,
    "unincorporated": EntityKind.UNINCORPORATED_BODY,
    "association": EntityKind.UNINCORPORATED_BODY,
    "society": EntityKind.UNINCORPORATED_BODY,
    "body of individuals": EntityKind.UNINCORPORATED_BODY,
}

#: Country name to ISO code, so a sheet saying "Singapore" and one saying "SG"
#: both end up comparable with a watchlist.
_BY_NAME = {name.lower(): code for code, name in COUNTRIES.items()}

_COUNTRY_FIELDS = ("nationality", "country_of_residence",
                   "country_of_incorporation", "jurisdiction")


#: Every spelling either vocabulary knows, flattened, so a candidate header
#: row can be scored without walking the tables each time.
_ALL_SPELLINGS = frozenset(
    s for spellings in FIELDS.values() for s in spellings
) | frozenset(
    s for spellings in PAYMENT_FIELDS.values() for s in spellings
)


def _key(header: str) -> str:
    return re.sub(r"[^a-z]", "", (header or "").lower())


def _country(value: str) -> str:
    """An ISO code where we can be sure, the original text where we cannot."""
    text = (value or "").strip()
    if len(text) == 2 and text.isalpha() and text.upper() in COUNTRIES:
        return text.upper()
    return _BY_NAME.get(text.lower(), text)


def _real_day(year: int, month: int, day: int) -> bool:
    """Whether these three numbers are a day that existed."""
    try:
        _date_type(year, month, day)
    except ValueError:
        return False
    return True


def _date(value: str) -> Optional[str]:
    """ISO date, or None if this is not unambiguously a date.

    Deliberately refuses 03/04/1980: that is 3 April in Mumbai and 4 March in
    New York, and a date of birth is a field screening compares. Guessing the
    wrong one turns a match into a miss.
    """
    text = (value or "").strip()
    if not text:
        return None
    iso = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if iso:
        year, month, day = (int(part) for part in iso.groups())
        return text if _real_day(year, month, day) else None
    match = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text)
    if match:
        first, second, year = (int(p) for p in match.groups())
        if first > 12 and second <= 12:          # unambiguously day-first
            day, month = first, second
        elif second > 12 and first <= 12:        # unambiguously month-first
            day, month = second, first
        else:
            return None                           # genuinely ambiguous
        if not _real_day(year, month, day):
            return None
        return f"{year:04d}-{month:02d}-{day:02d}"
    return None



def _named_date(text: str) -> Optional[str]:
    """"01-Aug-25" or "3 September 2026" as ISO; None if not this shape."""
    match = re.fullmatch(
        r"(\d{1,2})[-/\s]([a-z]{3,9})[-/\s](\d{2}|\d{4})",
        text.strip().lower())
    if not match:
        return None
    day, month_name, year_text = match.groups()
    month = _MONTHS.get(month_name[:3])
    if month is None:
        return None
    year = int(year_text)
    if year < 100:
        year += 2000 if year < 70 else 1900
    if not _real_day(year, month, int(day)):
        return None
    return f"{year:04d}-{month:02d}-{int(day):02d}"


def _date_shape(texts) -> tuple[str, str]:
    """How this column writes its dates, decided once for the whole column.

    One export writes one format, so a single row where the day is past the
    twelfth settles the question for every row. A column where no row
    settles it is refused: for money measured in two-day windows, a swapped
    month is not a formatting quibble, it is a wrong answer.
    """
    saw_day_first = saw_month_first = saw_ambiguous = False
    for text in texts:
        value = _clean(text)
        if (_blank(value) or re.match(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", value)
                or _named_date(value)):
            continue
        match = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-]\d{2,4}", value)
        if not match:
            continue                      # not a date at all; the row says so
        first, second = int(match.group(1)), int(match.group(2))
        if first > 12:
            saw_day_first = True
        elif second > 12:
            saw_month_first = True
        else:
            saw_ambiguous = True
    if saw_day_first and saw_month_first:
        return "", ("the date column mixes day-first and month-first "
                    "values, and one export cannot mean both. Write the "
                    "dates as YYYY-MM-DD, or with the month named, like "
                    "03-Apr-2026.")
    if saw_day_first:
        return "dayfirst", ""
    if saw_month_first:
        return "monthfirst", ""
    if saw_ambiguous:
        return "", ("every date in this sheet reads as two different days "
                    "\u2014 03/04/2026 is 3 April in Mumbai and 4 March in "
                    "New York \u2014 and nothing in the column settles "
                    "which. Write the dates as YYYY-MM-DD, or with the "
                    "month named, like 03-Apr-2026.")
    return "plain", ""


def _payment_date(text: str, shape: str) -> tuple[str, str]:
    """One cell as an ISO date under the column's decided shape."""
    value = _clean(text)
    if _blank(value):
        return "", "this row holds no date"
    iso = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", value)
    if iso:
        year, month, day = (int(part) for part in iso.groups())
        if not _real_day(year, month, day):
            return "", f"{value!r} is not a real date"
        return f"{year:04d}-{month:02d}-{day:02d}", ""
    named = _named_date(value)
    if named:
        return named, ""
    match = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})", value)
    if match:
        first, second, year = (int(part) for part in match.groups())
        if year < 100:
            year += 2000 if year < 70 else 1900
        if shape == "dayfirst" or (shape == "plain" and first > 12):
            day, month = first, second
        elif shape == "monthfirst" or (shape == "plain" and second > 12):
            day, month = second, first
        else:
            return "", f"{value!r} could be two different days"
        if not _real_day(year, month, day):
            return "", f"{value!r} is not a real date"
        return f"{year:04d}-{month:02d}-{day:02d}", ""
    return "", f"{value!r} is not a date"


# ---------------------------------------------------------------------------
# Reading a sheet that was not written for us
# ---------------------------------------------------------------------------

#: Excel on a Windows machine set to an Indian or European locale writes
#: cp1252, not UTF-8, and a rupee sign or a curly apostrophe in a name is
#: enough to make utf-8 decoding fail outright. Falling back is better than
#: refusing a file the firm can open perfectly well themselves.
_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")

#: Excel writes semicolons wherever the list separator is a semicolon, which
#: is most of Europe and some Indian installs. A tab-separated export saved
#: as .csv is also common.
_DELIMITERS = (",", ";", "\t", "|")

#: What a person writes in a cell to mean "nothing here". Treated as empty
#: rather than as a value, because "N/A" recorded as a date of birth is worse
#: than no date of birth.
_NOTHING = frozenset({
    "", "-", "--", "---", "n/a", "n.a.", "na", "nil", "none", "null",
    "not available", "not applicable", "unknown", "tbd", "tba", "?", ".",
})

#: Indian and international magnitudes, as they are actually typed. A sheet
#: from a Mumbai fund says "2.5 crore" far more often than "25000000".
_MAGNITUDES = (
    ("crore", 10_000_000), ("crores", 10_000_000), ("cr", 10_000_000),
    ("lakh", 100_000), ("lakhs", 100_000), ("lac", 100_000),
    ("lacs", 100_000), ("l", 100_000),
    ("billion", 1_000_000_000), ("bn", 1_000_000_000),
    ("million", 1_000_000), ("mn", 1_000_000), ("m", 1_000_000),
    ("thousand", 1_000), ("k", 1_000),
)

#: Honorifics glued onto names in registrar exports: "MR RAJESH KUMAR",
#: "SMT LATA IYER", "M/S ABC TRADING CO". No watchlist carries them, so a
#: name wearing one screens worse than the same name bare. Stripping is a
#: correction, and corrections are stated: the plan notes how many names
#: were affected.
_HONORIFIC = re.compile(
    r"^(?:mr|mrs|ms|dr|shri|smt|kum|master|mstr|prof|m/s|messrs)"
    r"[.\s]+(?=\S)", re.IGNORECASE)

#: Month names as dates actually write them: "01-Aug-25", "3 September 2026".
_MONTHS = {name: number for number, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}

#: Currency written into the amount cell rather than its own column.
_CURRENCY_MARKS = {
    "\u20b9": "INR", "rs.": "INR", "rs": "INR", "inr": "INR",
    "$": "USD", "usd": "USD", "us$": "USD",
    "\u20ac": "EUR", "eur": "EUR",
    "\u00a3": "GBP", "gbp": "GBP",
    "sgd": "SGD", "s$": "SGD", "aed": "AED", "jpy": "JPY", "\u00a5": "JPY",
}


def _clean(value: str) -> str:
    """Trim, and treat a non-breaking space as the space it looks like.

    Copy-and-paste out of a PDF or a web page brings U+00A0 with it, which is
    invisible and makes "Rajesh Iyer" and "Rajesh\u00a0Iyer" two different
    investors.
    """
    return re.sub(r"\s+", " ", (value or "").replace("\u00a0", " ")).strip()


def _blank(value: str) -> bool:
    return _clean(value).lower() in _NOTHING


def _money(text: str) -> tuple[Optional[float], str, str]:
    """(signed amount, currency found in the cell, problem).

    Real sheets write "USD 2,500,000", "\u20b91,00,00,000", "2.5 crore" and
    "(1,000)" for a negative. Each is unambiguous on its own; none survives a
    naive float(). The sign is kept: what a negative means is the caller's
    question, because for a commitment it is an error and for a statement
    line it is money leaving.
    """
    raw = _clean(text)
    if _blank(raw):
        return None, "", ""

    working = raw.lower()
    negative = (working.startswith("(") and working.endswith(")")
                or working.startswith("-"))
    working = working.strip("()").lstrip("-").strip()

    currency = ""
    for mark, code in sorted(_CURRENCY_MARKS.items(), key=lambda kv: -len(kv[0])):
        if working.startswith(mark):
            currency, working = code, working[len(mark):].strip()
            break
        if working.endswith(mark) and not working.endswith("l"):
            currency, working = code, working[:-len(mark)].strip()
            break

    multiplier = 1
    for word, factor in _MAGNITUDES:
        if working.endswith(word):
            head = working[: -len(word)].strip()
            # "50l" is fifty lakh; "50" followed by nothing is not.
            if head and re.fullmatch(r"[\d.,\s]+", head):
                multiplier, working = factor, head
                break

    # "1,000.00Cr" is a thousand credited, not a thousand crore -- but that
    # collision is settled before this function sees the cell, because
    # ``_payment_amount`` takes the direction marker off first. What reaches
    # here still wearing "cr" is a commitment written in crore.
    working = working.strip()
    # A comma with only one or two digits behind it is a decimal point, not
    # a grouping mark: no convention groups in twos, Indian or Western. That
    # makes "1.234,56" and "1234,56" readable by deduction rather than by
    # guessing -- and both come out of European and SWIFT-derived exports.
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d{1,2}", working):
        working = working.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d+,\d{1,2}", working):
        working = working.replace(",", ".")

    # Indian grouping (1,00,00,000) and Western grouping (10,000,000) both
    # reduce to the same number once the separators go.
    digits = re.sub(r"[,\s]", "", working)
    if not re.fullmatch(r"\d+(\.\d+)?", digits):
        return None, currency, f"{raw!r} is not an amount"

    return float(digits) * multiplier * (-1 if negative else 1), currency, ""


def _share(text: str) -> Optional[float]:
    """An ownership percentage: "25", "25%", "0.25" meaning a quarter --
    None where the cell says none of those."""
    written = _clean(text)
    per_cent = written.endswith("%")
    value = written.rstrip("%").strip()
    if _blank(value):
        return None
    try:
        share = float(value)
    except ValueError:
        return None
    # A bare number below one is the fraction UBO forms write; the same
    # number wearing a per-cent sign is half a per cent, and reading that
    # as fifty would hand an officer a controlling stake nobody declared.
    if 0 < share < 1 and not per_cent:
        share *= 100
    return share if 0 < share <= 100 else None


def _amount(text: str) -> tuple[Optional[float], str, str]:
    """A commitment amount: positive money or a stated problem."""
    value, currency, problem = _money(text)
    if problem or value is None:
        return None, currency, problem
    if value <= 0:
        return None, currency, (
            f"{_clean(text)!r} is not a commitment: an amount must be more "
            f"than nothing"
        )
    return value, currency, ""


def _payment_amount(text: str) -> tuple[Optional[float], str, str, str]:
    """(amount, currency, direction, problem) for one statement cell.

    Direction is read only where the cell itself states it: a trailing
    "Dr"/"Cr" the way Tally writes it, a bracketed or minus-signed figure
    the way accounting exports do. An unmarked figure says nothing about
    direction, and this function does not invent one.
    """
    raw = _clean(text)
    if _blank(raw):
        return None, "", "", ""
    direction = ""
    # The marker may be written flush against the figure ("1,000.00Cr"),
    # which core banking exports do routinely.
    marked = re.fullmatch(r"(.+?)\s*(dr|cr|debit|credit)\.?", raw,
                          re.IGNORECASE)
    if marked:
        raw = marked.group(1)
        direction = ("out" if marked.group(2).lower() in ("dr", "debit")
                     else "in")
    value, currency, problem = _money(raw)
    if problem or value is None:
        return None, currency, direction, problem
    if value < 0:
        value, direction = -value, "out"
    # Zero is returned as zero, not as a fault. On a statement with separate
    # withdrawal and deposit columns, the column this payment did not use
    # holds "0.00", and reading that as a broken row rejected every line of
    # the commonest bank export there is.
    return value, currency, direction, ""


def _decode(path: Path) -> str:
    for encoding in _ENCODINGS:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _delimiter(sample: str) -> str:
    """The separator that yields the most columns consistently.

    csv.Sniffer guesses from punctuation frequency and picks a comma out of
    prose in a preamble line often enough to matter, so this counts what each
    candidate actually produces instead.
    """
    best, best_score = ",", 0
    for candidate in _DELIMITERS:
        counts = [line.count(candidate) for line in sample.splitlines()[:40]
                  if line.strip()]
        if not counts:
            continue
        common = max(set(counts), key=counts.count)
        if common == 0:
            continue
        score = common * counts.count(common)
        if score > best_score:
            best, best_score = candidate, score
    return best


def _looks_like_header(cells: Sequence[str]) -> int:
    """How many cells in this row name a field we recognise."""
    return sum(1 for cell in cells if _key(cell) in _ALL_SPELLINGS)


def _read_sheet(path: Path) -> tuple[list[str], list[dict], list[str]]:
    """(headers, rows, notes). Finds the header wherever it actually is.

    Exports routinely open with a title, a "CONFIDENTIAL" line and a blank
    row before the real header. Anchoring on our own vocabulary rather than on
    "row 1" costs nothing and is what a person does when they open the file.
    """
    if xlsx.is_workbook(path):
        grid, notes = xlsx.grid(path)
        delimiter = ","
    else:
        text = _decode(path)
        delimiter = _delimiter(text)
        grid = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        notes = []

    header_at, best = 0, 0
    for index, row in enumerate(grid[:25]):
        score = _looks_like_header(row)
        if score > best:
            header_at, best = index, score
    if best == 0:
        return [], [], ["nothing in the first 25 rows looks like a header row"]
    if header_at:
        skipped = ("the row above it was skipped" if header_at == 1
                   else f"the {header_at} rows above it were skipped")
        notes.append(f"the header is on row {header_at + 1}; {skipped}")
    if delimiter != ",":
        shown = {"\t": "a tab", ";": "a semicolon", "|": "a pipe"}[delimiter]
        notes.append(f"columns are separated by {shown}, not a comma")

    headers, seen = [], {}
    for position, cell in enumerate(grid[header_at]):
        name = _clean(cell)
        if not name:
            name = f"(unnamed column {position + 1})"
        if name in seen:
            seen[name] += 1
            name = f"{name} ({seen[name]})"
        else:
            seen[name] = 1
        headers.append(name)

    rows = []
    for offset, line in enumerate(grid[header_at + 1:]):
        if not any(_clean(cell) for cell in line):
            continue                      # a blank row is a spacer, not a party
        row = {headers[i]: (line[i] if i < len(line) else "")
               for i in range(len(headers))}
        # The number a reader is told to go and look at is the number the
        # spreadsheet itself shows in its margin: counting from the header
        # would send them to the wrong line of any export with a banner.
        rows.append((header_at + 2 + offset, row))
    return headers, rows, notes


@dataclass
class Row:
    """One line of the sheet, and what we could make of it."""

    number: int
    name: str
    kind: Optional[EntityKind]
    attributes: dict[str, str] = field(default_factory=dict)
    commitment: Optional[dict[str, Any]] = None
    #: A declared owner, when the sheet names one: {"name", "share"}.
    owner: Optional[dict[str, Any]] = None
    #: The honorific that was stripped off the name, if one was.
    honorific: str = ""
    problems: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return not self.problems

    @property
    def entity_id(self) -> str:
        """Derived from the row's content, so importing the same sheet twice
        lands on the same party rather than a duplicate of them. PAN joins
        the identity only when the sheet carries one, so files without it
        keep the ids they always had."""
        parts = [self.name, str(self.kind or ""),
                 self.attributes.get("dob", ""),
                 self.attributes.get("id_document_number", "")]
        pan = self.attributes.get("pan", "")
        if pan:
            parts.append(pan)
        seed = "|".join(parts)
        return "imp_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def _party_id(name: str) -> str:
    """The id a payer known only by name lands on: the same derivation as a
    party row that carries nothing but a name."""
    seed = "|".join([name, str(EntityKind.UNKNOWN), "", ""])
    return "imp_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


@dataclass
class PaymentRow:
    """One statement line, and what we could make of it."""

    number: int
    payer: str = ""
    #: Who the money was for, where the sheet says. Where it does not, a
    #: payment is recorded against its sender, which is all that is known.
    beneficiary: str = ""
    amount: Optional[float] = None
    currency: str = ""
    date: str = ""
    reference: str = ""
    narration: str = ""
    #: Money leaving rather than arriving. Not an error -- just not what
    #: this register watches, so the row is counted and left out.
    outgoing: bool = False
    problems: list[str] = field(default_factory=list)
    #: Set when the plan is built: content-derived, with an occurrence
    #: index so two genuinely identical payments stay two payments while
    #: the same file imported twice stays one.
    payment_id: str = ""

    @property
    def usable(self) -> bool:
        return not self.problems and not self.outgoing

    @property
    def payer_id(self) -> str:
        return _party_id(self.payer) if self.payer else ""

    @property
    def beneficiary_id(self) -> str:
        return _party_id(self.beneficiary) if self.beneficiary else ""

    @property
    def subject(self) -> str:
        """Who this payment is about.

        The investor it was for, where the sheet names one -- that is the
        party whose file this belongs on, and it is also what gives the one
        surviving payment rule two parties to compare: recording the row
        against the sender instead would make every payment look as though
        the investor had paid for themselves.

        Failing that the sender, and failing that a deliberately unregistered
        id. That last case used to open a file saying "an unidentified
        sender"; since the rule that fired on a payment with no sender was
        removed on 21 August 2026 it opens nothing at all. The record is
        still written, which is right -- the payment happened and the log
        must say so -- but nobody is told about it.
        """
        return (self.beneficiary_id or self.payer_id
                or "unk_" + self.payment_id[4:])


@dataclass
class Plan:
    """What an import would do, before it does any of it."""

    #: "parties" or "payments" -- what the sheet's own columns say it is.
    kind: str = "parties"
    mapped: dict[str, str] = field(default_factory=dict)
    ignored: list[str] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    payments: list[PaymentRow] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)
    #: What reading the file itself required -- a header found below row 1, a
    #: separator that is not a comma. Reported so the reader can see we did
    #: not simply assume our way in.
    notes: list[str] = field(default_factory=list)

    @property
    def usable(self) -> list[Row]:
        return [r for r in self.rows if r.usable]

    @property
    def rejected(self) -> list[Row]:
        return [r for r in self.rows if not r.usable]

    @property
    def usable_payments(self) -> list[PaymentRow]:
        return [r for r in self.payments if r.usable]

    @property
    def rejected_payments(self) -> list[PaymentRow]:
        return [r for r in self.payments if r.problems]

    @property
    def outgoing_payments(self) -> list[PaymentRow]:
        return [r for r in self.payments if r.outgoing and not r.problems]


def _claims(headers, vocabulary):
    """Which recognised field each header claims to be, under one
    vocabulary."""
    claims: dict[str, list[str]] = {}
    unclaimed: list[str] = []
    for header in headers:
        key = _key(header)
        for target, spellings in vocabulary.items():
            if key in spellings:
                claims.setdefault(target, []).append(header)
                break
        else:
            unclaimed.append(header)
    return claims, unclaimed


def read(path: Path, default_kind: Optional[str] = None,
         sheet: str = "") -> Plan:
    """Work out what the sheet says. Writes nothing.

    The sheet's own columns decide whether it is a list of parties or a
    list of payments; ``sheet`` lets a caller answer for a file that could
    read as either, and that answer travels with the plan.
    """
    headers, raw_rows, notes = _read_sheet(Path(path))
    plan = Plan(notes=notes)
    if not headers:
        plan.refusals.append(
            "No row in this file looks like a header. Check it is the "
            "spreadsheet itself and not a report about it, and that the "
            "column names are on a row of their own."
        )
        return plan

    party_claims, party_unclaimed = _claims(headers, FIELDS)
    payment_claims, payment_unclaimed = _claims(headers, PAYMENT_FIELDS)

    told = (sheet or "").strip().lower()
    if told in ("parties", "party"):
        plan.kind = "parties"
    elif told in ("payments", "payment"):
        plan.kind = "payments"
    elif len(payment_claims) > len(party_claims):
        plan.kind = "payments"
    elif len(party_claims) > len(payment_claims):
        plan.kind = "parties"
    else:
        plan.refusals.append(
            "This sheet reads as well as a list of parties as it does as "
            "a list of payments, and choosing for you would put facts on "
            "the record nobody asserted. Say which it is."
        )
        return plan

    claims, unclaimed = ((payment_claims, payment_unclaimed)
                         if plan.kind == "payments"
                         else (party_claims, party_unclaimed))
    plan.ignored = [h for h in unclaimed
                    if not h.startswith("(unnamed column")]

    for target, columns in claims.items():
        if len(columns) > 1:
            named = ", ".join(f"\u201c{c}\u201d" for c in columns)
            plan.refusals.append(
                f"{len(columns)} columns could all be "
                f"{MEANINGS.get(target, target.replace('_', ' '))}: "
                f"{named}. Rename or remove all but one \u2014 choosing for "
                f"you would put a fact on the record that nobody asserted."
            )
        else:
            plan.mapped[target] = columns[0]
    if plan.refusals:
        return plan

    if plan.kind == "payments":
        return _read_payments(plan, raw_rows)
    return _read_parties(plan, raw_rows, default_kind)


def _read_parties(plan: Plan, raw_rows, default_kind) -> Plan:
    named = ("name" in plan.mapped or "first_name" in plan.mapped
             or "last_name" in plan.mapped)
    if not named:
        plan.refusals.append(
            "No column holds a party's name. One must be called Name, Full "
            "Name, Legal Name, Investor Name or similar."
        )
    if ("owner_name" in plan.mapped) != ("owner_share" in plan.mapped):
        missing = ("A column says who owns each party, but nothing says how "
                   "much of it they hold."
                   if "owner_name" in plan.mapped else
                   "A column holds an ownership share, but nothing says who "
                   "holds it.")
        plan.refusals.append(
            f"{missing} Ownership needs both a column naming the owner and "
            f"a column giving their percentage, or neither of them."
        )
    fallback = KINDS.get((default_kind or "").strip().lower())
    if "kind" not in plan.mapped and fallback is None:
        plan.refusals.append(
            "No column says what each party is. Add a column headed Type, "
            "holding one of: person, company, partnership, trust, fund, "
            "unincorporated. If every row in this file is the same kind, "
            "one column repeating that word is enough."
        )
    if plan.refusals:
        return plan

    for number, raw in raw_rows:
        plan.rows.append(_row(number, raw, plan.mapped, fallback))

    stripped = sum(1 for r in plan.rows if r.honorific)
    if stripped:
        names = "one name" if stripped == 1 else f"{stripped} names"
        plan.notes.append(
            f"honorifics such as MR, SMT and M/S were removed from "
            f"{names}; no watchlist carries them"
        )
    return plan


def _read_payments(plan: Plan, raw_rows) -> Plan:
    mapped = plan.mapped
    if "payer" not in mapped:
        plan.refusals.append(
            "No column says who each payment came from. A register that "
            "watches where money arrives from needs a Payer, Remitter or "
            "Sender column; a statement without one cannot be watched, "
            "only totalled."
        )
    split = "credit_amount" in mapped or "debit_amount" in mapped
    if "amount" not in mapped and not split:
        plan.refusals.append(
            "No column holds an amount. One must be called Amount, or the "
            "sheet must carry Credit and Debit columns the way a bank "
            "statement does."
        )
    date_column = mapped.get("value_date") or mapped.get("date")
    if not date_column:
        plan.refusals.append(
            "No column holds each payment's date, and payments without "
            "dates cannot be watched for patterns over days. One column "
            "must be headed Date, Value Date or Transaction Date."
        )
    if plan.refusals:
        return plan

    if "value_date" in mapped and "date" in mapped:
        plan.notes.append(
            "both a booking date and a value date are present; the value "
            "date -- the day the money took effect -- was used"
        )

    shape, why = _date_shape(raw.get(date_column, "")
                             for _, raw in raw_rows)
    if why:
        plan.refusals.append(why[0].upper() + why[1:])
        return plan

    counts: dict[tuple, int] = {}
    directionless = False
    for number, raw in raw_rows:
        row = _payment_row(number, raw, mapped, date_column, shape, split)
        if (row.usable and not split and "direction" not in mapped
                and row.amount is not None):
            directionless = True
        # Only the payments that will actually be recorded take a place in
        # the count. A rejected or outgoing row sharing the same details
        # used to consume an occurrence, so correcting an unrelated row
        # renumbered a payment that was already on the record and wrote it
        # a second time.
        if row.usable:
            key = (row.payer, row.amount, row.date, row.reference)
            counts[key] = counts.get(key, 0) + 1
            seed = "|".join([row.payer, str(row.amount), row.date,
                             row.reference, str(counts[key])])
            row.payment_id = (
                "pay_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12])
        plan.payments.append(row)

    if directionless:
        plan.notes.append(
            "the amounts carry no direction, so every row was read as "
            "money arriving"
        )
    left_out = len(plan.outgoing_payments)
    if left_out:
        rows = ("one row is" if left_out == 1
                else f"{left_out} rows are")
        plan.notes.append(
            f"{rows} money going out, not arriving; this register "
            f"watches what arrives, so "
            f"{'it was' if left_out == 1 else 'they were'} left out"
        )
    return plan


def _payment_row(number, raw, mapped, date_column, shape,
                 split) -> PaymentRow:
    row = PaymentRow(number=number)
    row.payer = _clean(raw.get(mapped["payer"]) or "")
    if _blank(row.payer):
        row.payer = ""
    stripped = _HONORIFIC.sub("", row.payer)
    if stripped != row.payer:
        row.payer = _clean(stripped)

    stated = _clean(raw.get(mapped.get("currency", "")) or "")
    stated = "" if _blank(stated) else stated.upper()
    in_cell = ""

    if split:
        credit_text = raw.get(mapped.get("credit_amount", ""), "")
        debit_text = raw.get(mapped.get("debit_amount", ""), "")
        credit, cur_c, dir_c, problem_c = _payment_amount(credit_text)
        debit, cur_d, dir_d, problem_d = _payment_amount(debit_text)
        if credit == 0:
            credit = None          # the column this payment did not use
        if debit == 0:
            debit = None
        if problem_c:
            row.problems.append(problem_c)
        elif problem_d:
            row.problems.append(problem_d)
        elif credit is not None and debit is not None:
            row.problems.append(
                "both the credit and the debit column carry money; one "
                "payment cannot go both ways")
        elif credit is not None:
            # A negative or bracketed figure in the deposit column is a
            # reversal: money leaving, however it was filed.
            row.amount, in_cell = credit, cur_c
            row.outgoing = dir_c == "out"
        elif debit is not None:
            row.amount, in_cell = debit, cur_d
            row.outgoing = dir_d != "in"
        else:
            row.problems.append("neither column holds an amount")
    else:
        amount, in_cell, direction, problem = _payment_amount(
            raw.get(mapped["amount"], ""))
        if problem:
            row.problems.append(problem)
        elif amount is None:
            row.problems.append("this row holds no amount")
        elif amount == 0:
            row.problems.append(
                f"{_clean(raw.get(mapped['amount'], ''))!r} is a payment "
                f"of nothing")
        else:
            row.amount = amount
            told = _clean(raw.get(mapped.get("direction", "")) or "").lower()
            told = "" if _blank(told) else told
            if told in ("c", "cr", "crdt", "credit", "deposit", "in"):
                direction = "in"
            elif told in ("d", "dr", "dbit", "debit", "withdrawal", "out",
                          "rd", "rc"):
                direction = "out"
            elif told:
                row.problems.append(
                    f"{told!r} does not say whether money came in or went "
                    f"out")
            row.outgoing = direction == "out"

    row.currency = stated or in_cell

    date_iso, problem = _payment_date(raw.get(date_column, ""), shape)
    if problem:
        row.problems.append(problem)
    else:
        row.date = date_iso

    row.beneficiary = _clean(raw.get(mapped.get("beneficiary", "")) or "")
    if _blank(row.beneficiary):
        row.beneficiary = ""
    row.beneficiary = _clean(_strip_honorific(row.beneficiary))

    row.reference = _clean(raw.get(mapped.get("reference", "")) or "")
    if _blank(row.reference):
        row.reference = ""
    row.narration = _clean(raw.get(mapped.get("narration", "")) or "")
    if _blank(row.narration):
        row.narration = ""
    return row


def _strip_honorific(name: str) -> str:
    """A name without the courtesy title in front of it.

    Only where something recognisable is left: "MS Dhoni" is a person whose
    initials are M and S, and taking the "MS" off would leave a surname and
    screen the wrong party. Two words have to survive for the leading word
    to have been a title rather than part of the name.
    """
    bare = _HONORIFIC.sub("", name or "")
    if bare == name:
        return name
    return bare if len(bare.split()) >= 2 else name


def _name_of(raw, mapped) -> str:
    """The party's one name, whole or joined from its registrar pieces."""
    if "name" in mapped:
        whole = _clean(raw.get(mapped["name"]) or "")
        if not _blank(whole):
            return whole
    pieces = [_clean(raw.get(mapped.get(part, "")) or "")
              for part in ("first_name", "middle_name", "last_name")]
    return _clean(" ".join(piece for piece in pieces
                           if not _blank(piece)))


def _row(number, raw, mapped, fallback) -> Row:
    name = _name_of(raw, mapped)
    row = Row(number=number, name=name, kind=fallback)

    bare = _strip_honorific(name)
    if bare != name:
        row.honorific = name[: len(name) - len(bare)].strip()
        row.name = name = _clean(bare)

    if not name:
        row.problems.append("this row names no party")

    if "kind" in mapped:
        spelling = _clean(raw.get(mapped["kind"]) or "").lower()
        kind = KINDS.get(spelling)
        if kind is None and spelling:
            row.problems.append(
                f"\u201c{spelling}\u201d is not a kind of party this "
                f"recognises")
        elif kind is None and fallback is None:
            row.problems.append(
                "this row does not say what kind of party it is")
        else:
            row.kind = kind or fallback

    for target, column in mapped.items():
        if target in ("name", "first_name", "middle_name", "last_name",
                      "kind", "commitment_amount", "commitment_currency",
                      "fund", "owner_name", "owner_share"):
            continue
        value = _clean(raw.get(column) or "")
        if _blank(value):
            continue
        if target in _COUNTRY_FIELDS:
            value = _country(value)
        elif target in ("dob", "date_of_incorporation"):
            iso = _date(value)
            if iso is None:
                row.problems.append(
                    f"{value!r} could be two different dates; write it as "
                    f"YYYY-MM-DD"
                )
                continue
            value = iso
        row.attributes[target] = value

    if "owner_name" in mapped:
        owner = _clean(raw.get(mapped["owner_name"]) or "")
        share_text = _clean(raw.get(mapped["owner_share"]) or "")
        if not _blank(owner) or not _blank(share_text):
            share = _share(share_text)
            if _blank(owner):
                row.problems.append(
                    "a share is declared but nobody is named as holding it")
            elif share is None:
                row.problems.append(
                    f"{share_text!r} is not a share; write a percentage "
                    f"between 0 and 100")
            else:
                bare_owner = _clean(_strip_honorific(owner))
                row.owner = {"name": bare_owner or owner, "share": share}

    if "commitment_amount" in mapped:
        amount, in_cell, problem = _amount(raw.get(mapped["commitment_amount"]))
        if problem:
            row.problems.append(problem)
        elif amount is not None:
            # A currency column wins over one written into the amount cell:
            # the column is the firm saying so deliberately.
            stated = _clean(raw.get(mapped.get("commitment_currency", "")) or "")
            currency = ("" if _blank(stated) else stated.upper()) or in_cell
            if not currency:
                row.problems.append(
                    f"{_clean(raw.get(mapped['commitment_amount'])) !r} has no "
                    f"currency; add a currency column or write it in the cell"
                )
            else:
                fund = _clean(raw.get(mapped.get("fund", "")) or "")
                row.commitment = {
                    "amount": amount,
                    "currency": currency,
                    "fund": "the fund" if _blank(fund) else fund,
                }
    return row


def already_imported(engine, digest: str) -> str:
    """The sentence that refuses a byte-identical re-import, or nothing."""
    record = engine.state.imports.get(digest)
    if not record:
        return ""
    return (
        f"This exact file was already imported on {_written_date(record['on'])}"
        f" by {record['by']}. Importing it again would say everything in it "
        f"happened twice. If rows were corrected, the corrected file will "
        f"differ and will be accepted."
    )


#: Months as a reader writes them, so a refusal does not answer in the
#: notation a machine stores.
_MONTH_NAMES = ("January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November",
                "December")


def _written_date(iso: str) -> str:
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", (iso or "").strip())
    if not match:
        return iso or ""
    year, month, day = (int(part) for part in match.groups())
    if not 1 <= month <= 12:
        return iso
    return f"{day} {_MONTH_NAMES[month - 1]} {year}"


def apply(engine, plan: Plan, on: str, *, by: str = "import",
          filename: str = "", digest: str = "") -> dict[str, int]:
    """Write the usable rows into the log. Call only after a person has seen
    the plan: an append-only log has no undo.

    The whole import is one indivisible act. Every guard here reads the log
    and then writes to it -- "was this file already imported", "is this
    payment already recorded" -- and two officers confirming the same sheet
    at the same moment would each read *before* the other wrote, and put
    every row on the record twice. Permanently, because nothing can be
    removed. The engine's lock is re-entrant, so the ingest calls below are
    safe inside it.
    """
    with engine._lock:                 # noqa: SLF001 -- see the docstring
        if plan.refusals:
            raise ValueError("this sheet was refused; nothing was written")
        if digest:
            repeat = already_imported(engine, digest)
            if repeat:
                raise ValueError(repeat)

        if plan.kind == "payments":
            counts = _apply_payments(engine, plan, by)
        else:
            counts = _apply_parties(engine, plan, on)

        if digest:
            engine.ingest(
                event_type=EventType.SHEET_IMPORTED,
                subject="sht_" + digest[:12],
                occurred_at=on,
                actor=by,
                payload={
                    "file": filename,
                    "digest": digest,
                    "sheet": plan.kind,
                    "columns": dict(plan.mapped),
                    "counts": dict(counts),
                    "rows_rejected": (len(plan.rejected)
                                      + len(plan.rejected_payments)),
                },
            )
        return counts


def _apply_parties(engine, plan: Plan, on: str) -> dict[str, int]:
    known = engine.state.graph.entities
    promised = {
        event.payload.get("commitment_id")
        for event in engine.log
        if event.event_type is EventType.COMMITMENT_MADE
    }
    counts = {"registered": 0, "already_known": 0, "committed": 0,
              "ownership_declared": 0}
    for row in plan.usable:
        entity_id = row.entity_id
        if entity_id in known:
            counts["already_known"] += 1
        else:
            engine.ingest(
                event_type=EventType.ENTITY_REGISTERED,
                subject=entity_id,
                occurred_at=on,
                actor="import",
                payload={"kind": str(row.kind), "name": row.name,
                         "attributes": dict(row.attributes)},
            )
            counts["registered"] += 1
        if row.commitment:
            # Derived from what the commitment says, not from who made it:
            # one investor can commit to two funds, and an id that ignored
            # the fund made the second commitment overwrite the first. It
            # also makes re-importing a corrected sheet leave the
            # commitments it already recorded alone.
            seed = "|".join([entity_id, str(row.commitment.get("fund", "")),
                             str(row.commitment.get("amount", "")),
                             str(row.commitment.get("currency", ""))])
            commitment_id = "cim_" + hashlib.sha256(
                seed.encode("utf-8")).hexdigest()[:12]
            if commitment_id in promised:
                counts["already_known"] += 0      # already on the record
            else:
                engine.ingest(
                    event_type=EventType.COMMITMENT_MADE,
                    subject=entity_id,
                    occurred_at=on,
                    actor="import",
                    payload={"investor": entity_id,
                             "commitment_id": commitment_id,
                             **row.commitment},
                )
                promised.add(commitment_id)
                counts["committed"] += 1
        if row.owner:
            owner_id = _party_id(row.owner["name"])
            if owner_id not in engine.state.graph.entities:
                engine.ingest(
                    event_type=EventType.ENTITY_REGISTERED,
                    subject=owner_id,
                    occurred_at=on,
                    actor="import",
                    payload={"kind": str(EntityKind.UNKNOWN),
                             "name": row.owner["name"], "attributes": {}},
                )
                counts["registered"] += 1
            engine.ingest(
                event_type=EventType.OWNERSHIP_DECLARED,
                subject=entity_id,
                occurred_at=on,
                actor="import",
                payload={"owner": owner_id, "owned": entity_id,
                         "percentage": row.owner["share"],
                         "relation": "OWNS",
                         "edge_id": "edg_" + hashlib.sha256(
                             f"{owner_id}|{entity_id}".encode("utf-8")
                         ).hexdigest()[:12]},
            )
            counts["ownership_declared"] += 1
    return counts


def _apply_payments(engine, plan: Plan, by: str) -> dict[str, int]:
    """Each statement line becomes an ordinary payment fact, written in
    date order so a pattern spread across days is visible to the rules the
    moment its last payment lands."""
    recorded = {
        event.payload.get("payment_id")
        for event in engine.log
        if event.event_type is EventType.PAYMENT_RECEIVED
    }
    counts = {"payments_recorded": 0, "payers_registered": 0,
              "already_recorded": 0}
    for row in sorted(plan.usable_payments, key=lambda r: r.date):
        if row.payment_id in recorded:
            counts["already_recorded"] += 1
            continue
        if (row.beneficiary
                and row.beneficiary_id not in engine.state.graph.entities):
            engine.ingest(
                event_type=EventType.ENTITY_REGISTERED,
                subject=row.beneficiary_id,
                occurred_at=row.date,
                actor="import",
                payload={"kind": str(EntityKind.UNKNOWN),
                         "name": row.beneficiary, "attributes": {}},
            )
            counts["payers_registered"] += 1
        if row.payer and row.payer_id not in engine.state.graph.entities:
            engine.ingest(
                event_type=EventType.ENTITY_REGISTERED,
                subject=row.payer_id,
                occurred_at=row.date,
                actor="import",
                payload={"kind": str(EntityKind.UNKNOWN),
                         "name": row.payer, "attributes": {}},
            )
            counts["payers_registered"] += 1
        payload = {
            "payment_id": row.payment_id,
            "payment_ref": row.reference,
            "amount": row.amount,
            "currency": row.currency,
            "payer": row.payer_id,
        }
        if row.narration:
            payload["narration"] = row.narration
        engine.ingest(
            event_type=EventType.PAYMENT_RECEIVED,
            subject=row.subject,
            occurred_at=row.date,
            actor="import",
            payload=payload,
        )
        counts["payments_recorded"] += 1
    return counts


def describe(plan: Plan, path: Path) -> str:
    """The plan, in words, for someone deciding whether to run it."""
    out = [f"  {path}"]
    if plan.notes:
        out.append("")
        out.append("  Reading this file:")
        out.extend(f"    - {note}" for note in plan.notes)
    if plan.refusals:
        out.append("")
        out.append("  This sheet was not imported:")
        out.extend(f"    - {r}" for r in plan.refusals)
        return "\n".join(out)

    out.append("")
    out.append("  Columns being used:")
    out.extend(f"    {column:<28} -> {target.replace('_', ' ')}"
               for target, column in sorted(plan.mapped.items(),
                                            key=lambda kv: kv[1]))
    if plan.ignored:
        out.append("")
        out.append("  Columns ignored, because nothing here recognises them:")
        out.extend(f"    {c}" for c in plan.ignored)

    out.append("")
    if plan.kind == "payments":
        usable = len(plan.usable_payments)
        out.append(f"  This sheet reads as payments. {usable} "
                   f"{'payment' if usable == 1 else 'payments'} would be "
                   f"recorded.")
        going = len(plan.outgoing_payments)
        if going:
            out.append(f"  {going} {'row is' if going == 1 else 'rows are'} "
                       f"money going out and would be left out.")
        rejected = plan.rejected_payments
    else:
        usable = len(plan.usable)
        out.append(f"  This sheet reads as parties. {usable} "
                   f"{'row' if usable == 1 else 'rows'} would be imported.")
        rejected = plan.rejected
    if rejected:
        out.append(f"  {len(rejected)} "
                   f"{'row' if len(rejected) == 1 else 'rows'} would be "
                   f"left out:")
        for row in rejected[:10]:
            out.append(f"    row {row.number}: {'; '.join(row.problems)}")
        if len(rejected) > 10:
            more = len(rejected) - 10
            out.append(f"    ... and {more} "
                       f"{'other' if more == 1 else 'others'}")
    return "\n".join(out)
