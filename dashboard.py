from flask import Flask, render_template, request, jsonify, send_file
import pandas as pd
import io, os, re, uuid

app = Flask(__name__, template_folder='templates')

HEADER = (
    '<ENVELOPE>\n<HEADER>\n<TALLYREQUEST>Import Data</TALLYREQUEST>\n</HEADER>\n'
    '<BODY>\n<IMPORTDATA>\n<REQUESTDESC>\n<REPORTNAME>All Masters</REPORTNAME>\n'
    '</REQUESTDESC>\n<REQUESTDATA>\n'
)
FOOTER = '</REQUESTDATA>\n</IMPORTDATA>\n</BODY>\n</ENVELOPE>\n'

# In-memory XML store: token -> xml string
xml_store: dict[str, str] = {}

CURRENCY_MAP = {'RM': 'MYR', '$': 'USD', '₹': 'INR'}

# ---------- helpers ----------------------------------------------------------

def esc(v: str) -> str:
    return (str(v)
            .replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace("'", '&apos;').replace('"', '&quot;'))


def parse_num(v) -> float | None:
    s = str(v).strip()
    if s.lower() in ('emp', 'nan', ''):
        return None
    s = s.replace(',', '')
    m = re.search(r'-?\d+\.?\d*', s)
    return float(m.group()) if m else None


def parse_currency(raw: str):
    """Return (float_value, currency_symbol) from strings like 'USD 88.54', 'RM558000', '$1,234'."""
    s = str(raw or '').strip()
    if not s or s.lower() == 'emp':
        return None, ''
    neg = s.startswith('(') and s.endswith(')')
    if neg:
        s = s[1:-1].strip()
    symbol = ''
    for pref in ('RM', '$', '₹'):
        if s.startswith(pref):
            symbol = pref
            s = s[len(pref):].strip()
            break
    s = re.sub(r'[^0-9.\-]', '', s.replace(',', ''))
    if not s or s == '.':
        return None, symbol
    val = float(s)
    return (-val if neg else val), symbol


def safe_float(x, default=None):
    try:
        return float(x)
    except Exception:
        return default


def is_truly_empty(v) -> bool:
    s = str(v).strip()
    return s == '' or s.lower() == 'nan'


# ---------- validation -------------------------------------------------------

REQUIRED_PREFIXES = {
    'cn':       ['DATE', 'VOUCHERTYPENAME', 'VOUCHERNUMBER', 'Reference', 'Buyer_Name', 'CreditLedger'],
    'jv':       ['DATE', 'VOUCHERTYPENAME', 'DebitLedger', 'AmountDebit', 'CreditLedger', 'AmountCredit'],
    'sale':     ['DATE', 'VOUCHERTYPENAME', 'VOUCHERNUMBER', 'Reference', 'Buyer_Name', 'DebitLedger', 'AmountDebit'],
    'sale_usd': ['DATE', 'VOUCHERTYPENAME', 'VOUCHERNUMBER', 'Reference', 'Buyer_Name', 'DebitLedger', 'AmountDebit'],
    'nexus':    ['DATE', 'VOUCHERTYPENAME', 'VOUCHERNUMBER', 'Buyer_Name', 'DebitLedger', 'AmountDebit'],
    'receipt':  ['DATE', 'VOUCHERTYPENAME', 'VOUCHERNUMBER', 'DebitLedger', 'AmountDebit', 'CreditLedger', 'AmountCredit', 'Invoice'],
}

# Prefixes that are identifiers/metadata — skip from amount sums
_SKIP_SUM_PREFIXES = (
    'DATE', 'VOUCHER', 'Reference', 'Narration', 'NARRATION', 'Buyer_',
    'Address_', 'Pincode', 'State_', 'Registration_', 'Company_', 'POS',
    'Country', 'Cost_Category', 'Cost_Centre', 'entry_code', 'Mode',
    'DebitLedger', 'CreditLedger', 'EX_RATE',
)


def _is_amount_col(col: str, vals, row_count: int) -> bool:
    """True only for columns whose values are mostly plain numbers."""
    col_clean = col.strip().lstrip('﻿')
    if col_clean.startswith(_SKIP_SUM_PREFIXES):
        return False
    # Must start with Amount / IGST / SGST / CGST, or be a plain numeric column
    is_accounting = col_clean.startswith(('Amount', 'IGST', 'SGST', 'CGST'))
    nums = [parse_num(v) for v in vals]
    valid = [n for n in nums if n is not None]
    if not valid:
        return False
    # For non-accounting named cols, require >70% numeric AND values look like money
    coverage = len(valid) / max(row_count, 1)
    return is_accounting and coverage >= 0.4 or (coverage >= 0.7 and not col_clean.startswith(_SKIP_SUM_PREFIXES))


def validate(df: pd.DataFrame, doc_type: str) -> dict:
    # Strip BOM from column names (jv.csv saved with UTF-8 BOM)
    df.columns = [c.lstrip('﻿').strip() for c in df.columns]
    cols = list(df.columns)
    result: dict = {
        'total_rows': len(df),
        'columns': cols,
        'amount_sums': {},
        'missing': [],
        'balance': None,
    }

    # Sum only genuine amount / GST columns
    for col in cols:
        col_vals = list(df[col])
        if _is_amount_col(col, col_vals, len(df)):
            nums = [parse_num(v) for v in col_vals if parse_num(v) is not None]
            result['amount_sums'][col] = round(sum(nums), 2)

    # Required-field check: flag truly-empty cells (NaN / blank, not 'emp')
    for prefix in REQUIRED_PREFIXES.get(doc_type, []):
        matched_col = next((c for c in cols if c.startswith(prefix)), None)
        if matched_col is None:
            result['missing'].append({'row': '—', 'field': prefix, 'issue': 'Column not found in CSV'})
            continue
        for idx in range(len(df)):
            if is_truly_empty(df[matched_col].iloc[idx]):
                result['missing'].append({
                    'row': idx + 2,   # +1 for 0-index, +1 for header row
                    'field': matched_col,
                    'issue': 'Empty / NaN',
                })

    # JV: debit-credit balance check
    if doc_type == 'jv':
        dc = next((c for c in cols if c.startswith('AmountDebit')), None)
        cc = next((c for c in cols if c.startswith('AmountCredit')), None)
        if dc and cc:
            ds = sum(parse_num(v) or 0 for v in df[dc])
            cs = sum(parse_num(v) or 0 for v in df[cc])
            result['balance'] = {
                'debit':  round(ds, 2),
                'credit': round(cs, 2),
                'ok': abs(abs(ds) - abs(cs)) < 0.02,
            }

    return result


# ---------- converters -------------------------------------------------------

def _address_block(l1, l2, l3, l4) -> str:
    return (
        f'<ADDRESS.LIST TYPE="String">\n'
        f'<ADDRESS>{l1}</ADDRESS>\n<ADDRESS>{l2}</ADDRESS>\n'
        f'<ADDRESS>{l3}</ADDRESS>\n<ADDRESS>{l4}</ADDRESS>\n'
        f'</ADDRESS.LIST>\n'
        f'<BASICBUYERADDRESS.LIST TYPE="String">\n'
        f'<BASICBUYERADDRESS>{l1}</BASICBUYERADDRESS>\n'
        f'<BASICBUYERADDRESS>{l2}</BASICBUYERADDRESS>\n'
        f'<BASICBUYERADDRESS>{l3}</BASICBUYERADDRESS>\n'
        f'<BASICBUYERADDRESS>{l4}</BASICBUYERADDRESS>\n'
        f'</BASICBUYERADDRESS.LIST>\n'
    )


def convert_cn(df: pd.DataFrame) -> str:
    att = df.columns
    srop = ''
    for j in range(len(df)):
        rowop = ''
        v_type = inv_no = cost_category = ''
        line1 = line2 = line3 = line4 = ''

        for i in range(len(att)):
            col = att[i]
            rv = esc(str(df[col].iloc[j]))

            if col.startswith('DATE'):
                rowop += f'<{col}>{rv}</{col}>\n<REFERENCEDATE>{rv}</REFERENCEDATE>\n'
                continue
            if col.startswith('VOUCHERTYPENAME'):
                v_type = rv
                rowop += (f'<VOUCHERTYPENAME>{rv}</VOUCHERTYPENAME>\n'
                          f'<VOUCHERTYPEORIGNAME>{rv}</VOUCHERTYPEORIGNAME>\n'
                          f'<VCHENTRYMODE>Accounting Invoice</VCHENTRYMODE>\n')
                continue
            if col.startswith('VOUCHERNUMBER'):
                rowop += f'<VOUCHERNUMBER>{rv}</VOUCHERNUMBER>\n'
                continue
            if col.startswith('Reference'):
                inv_no = rv
                rowop += f'<REFERENCE>{rv}</REFERENCE>\n'
                continue
            if col.startswith('Cost_Category'):
                cost_category = rv
                continue
            if col.startswith('NARRATION'):
                rowop += f'<NARRATION>{rv}</NARRATION>\n'
                continue
            if col.startswith('Buyer_Name'):
                rowop += (f'<BASICBUYERNAME>{rv}</BASICBUYERNAME>\n'
                          f'<CONSIGNEEMAILINGNAME>{rv}</CONSIGNEEMAILINGNAME>\n'
                          f'<PARTYNAME>{rv}</PARTYNAME>\n'
                          f'<PARTYMAILINGNAME>{rv}</PARTYMAILINGNAME>\n')
                continue
            if col.startswith('Pincode'):
                if rv != 'emp':
                    rowop += f'<PARTYPINCODE>{rv}</PARTYPINCODE>\n<CONSIGNEEPINCODE>{rv}</CONSIGNEEPINCODE>\n'
                continue
            if col.startswith('State_Name'):
                if rv != 'emp':
                    rowop += (f'<STATENAME>{rv}</STATENAME>\n'
                              f'<BILLTOPLACE>{rv}</BILLTOPLACE>\n'
                              f'<CONSIGNEESTATENAME>{rv}</CONSIGNEESTATENAME>\n')
                continue
            if col.startswith('Address_1'):
                line1 = '' if rv == 'emp' else rv
                continue
            if col.startswith('Address_2'):
                line2 = '' if rv == 'emp' else rv
                continue
            if col.startswith('Address_3'):
                line3 = '' if rv == 'emp' else rv
                continue
            if col.startswith('Address_4'):
                line4 = '' if rv == 'emp' else rv
                rowop += _address_block(line1, line2, line3, line4)
                continue
            if col.startswith('POS'):
                rowop += f'<PLACEOFSUPPLY>{rv}</PLACEOFSUPPLY>\n<SHIPTOPLACE>{rv}</SHIPTOPLACE>\n'
                continue
            if col.startswith('Country'):
                rowop += f'<COUNTRYOFRESIDENCE>{rv}</COUNTRYOFRESIDENCE>'
                continue
            if col.startswith('Registration_Type'):
                continue
            if col.startswith('Company_GSTIN'):
                if rv != 'emp':
                    rowop += f'<PARTYGSTIN>{rv}</PARTYGSTIN>\n<CONSIGNEEGSTIN>{rv}</CONSIGNEEGSTIN>\n'
                continue
            if col.startswith('CreditLedger'):
                if rv != 'emp':
                    rowop += (f'<PARTYLEDGERNAME>{rv}</PARTYLEDGERNAME>\n'
                              f'<LEDGERENTRIES.LIST>\n<LEDGERNAME>{rv}</LEDGERNAME>\n')
                continue
            if col.startswith('AmountCredit'):
                if rv != 'emp':
                    rowop += (f'<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>\n'
                              f'<ISPARTYLEDGER>No</ISPARTYLEDGER>\n'
                              f'<AMOUNT>{rv}</AMOUNT>\n'
                              f'<BILLALLOCATIONS.LIST>\n<NAME>{inv_no}</NAME>\n'
                              f'<BILLTYPE>{inv_no}</BILLTYPE>\n'
                              f'<AMOUNT>{rv}</AMOUNT>\n'
                              f'</BILLALLOCATIONS.LIST>\n</LEDGERENTRIES.LIST>')
                continue

            # Generic ledger entries (Extension Fees, Cost_Centre, GST)
            l_name = col
            if i == len(att) - 1 and rv == 'emp':
                rowop += '</VOUCHER>\n</TALLYMESSAGE>\n'
            if rv == 'emp':
                continue
            if not l_name.startswith(('CGST', 'IGST', 'SGST')):
                if col.startswith('Cost_Centre'):
                    continue
                nv = esc(str(df[att[i + 1]].iloc[j])) if i + 1 < len(att) else ''
                rowop += (f'<LEDGERENTRIES.LIST>\n<LEDGERNAME>{l_name}</LEDGERNAME>\n'
                          f'<GSTCLASS/>\n<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>\n'
                          f'<ISPARTYLEDGER>Yes</ISPARTYLEDGER>\n<AMOUNT>{rv}</AMOUNT>\n'
                          f'<CATEGORYALLOCATIONS.LIST>\n<CATEGORY>{cost_category}</CATEGORY>\n'
                          f'<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>\n'
                          f'<COSTCENTREALLOCATIONS.LIST>\n<NAME>{nv}</NAME>\n'
                          f'<AMOUNT>{rv}</AMOUNT>\n</COSTCENTREALLOCATIONS.LIST>\n'
                          f'</CATEGORYALLOCATIONS.LIST>\n</LEDGERENTRIES.LIST>\n')
            else:
                close = '\n</VOUCHER>\n</TALLYMESSAGE>\n' if i == len(att) - 1 else ''
                pos = 'yes' if i == len(att) - 1 else 'Yes'
                rowop += (f'<LEDGERENTRIES.LIST>\n<LEDGERNAME>{l_name}</LEDGERNAME>\n'
                          f'<GSTCLASS/>\n<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>\n'
                          f'<ISPARTYLEDGER>{pos}</ISPARTYLEDGER>\n<AMOUNT>{rv}</AMOUNT>\n'
                          f'</LEDGERENTRIES.LIST>{close}\n')

        srop += (f'<TALLYMESSAGE xmlns:UDF="TallyUDF">\n'
                 f'<VOUCHER VCHTYPE="{v_type}" ACTION="Create" OBJVIEW="Accounting Voucher View">\n'
                 f'{rowop}')

    return HEADER + srop + FOOTER


def convert_jv(df: pd.DataFrame) -> str:
    columns = df.columns
    final_xml = ''
    v_type = ''

    for row_idx in range(len(df)):
        row_data = ''
        for col_idx in range(len(columns)):
            col = columns[col_idx]
            value = str(df[col].iloc[row_idx]).strip()
            if value.lower() == 'emp':
                continue
            value = esc(value)

            if col.startswith(('entry_code', 'Mode')):
                continue
            if col.startswith('VOUCHERTYPENAME'):
                v_type = value
                try:
                    party = esc(str(df[columns[col_idx + 4]].iloc[row_idx]))
                except Exception:
                    party = ''
                row_data += (f'<PARTYLEDGERNAME>{party}</PARTYLEDGERNAME>\n'
                             f'<{col}>{value}</{col}>\n'
                             f'<REFERENCE>On Account</REFERENCE>\n')
                continue
            if col.startswith('DebitLedger'):
                row_data += f'<ALLLEDGERENTRIES.LIST>\n<LEDGERNAME>{value}</LEDGERNAME>\n'
                continue
            if col.startswith('AmountDebit'):
                row_data += (f'<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>\n'
                             f'<AMOUNT>{value}</AMOUNT>\n</ALLLEDGERENTRIES.LIST>\n')
                continue
            if col.startswith('CreditLedger'):
                row_data += f'<ALLLEDGERENTRIES.LIST>\n<LEDGERNAME>{value}</LEDGERNAME>\n'
                continue
            if col.startswith('AmountCredit'):
                row_data += (f'<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>\n'
                             f'<AMOUNT>{value}</AMOUNT>\n</ALLLEDGERENTRIES.LIST>\n')
                if col_idx == len(columns) - 1:
                    row_data += '</VOUCHER>\n</TALLYMESSAGE>\n'
                continue
            if col.startswith('DATE'):
                row_data += f'<{col}>{value}</{col}>\n'
                continue
            row_data += f'<{col}>{value}</{col}>\n'

        final_xml += (f'<TALLYMESSAGE xmlns:UDF="TallyUDF">\n'
                      f'<VOUCHER VCHTYPE="{v_type}" ACTION="Create" OBJVIEW="Accounting Voucher View">\n'
                      f'{row_data}')

    return HEADER + final_xml + FOOTER


def convert_sale(df: pd.DataFrame) -> str:
    att = df.columns
    srop = ''
    for j in range(len(df)):
        rowop = ''
        v_type = inv_no = cost_category = ''
        line1 = line2 = line3 = line4 = ''

        for i in range(len(att)):
            col = att[i]
            rv = esc(str(df[col].iloc[j]))

            if col.startswith('DATE'):
                rowop += f'<{col}>{rv}</{col}>\n<REFERENCEDATE>{rv}</REFERENCEDATE>\n'
                continue
            if col.startswith('VOUCHERTYPENAME'):
                v_type = rv
                rowop += (f'<VOUCHERTYPENAME>{rv}</VOUCHERTYPENAME>\n'
                          f'<VOUCHERTYPEORIGNAME>{rv}</VOUCHERTYPEORIGNAME>\n'
                          f'<VCHENTRYMODE>Accounting Invoice</VCHENTRYMODE>\n')
                continue
            if col.startswith('VOUCHERNUMBER'):
                rowop += f'<VOUCHERNUMBER>{rv}</VOUCHERNUMBER>\n'
                continue
            if col.startswith('Reference'):
                inv_no = rv
                rowop += f'<REFERENCE>{rv}</REFERENCE>\n'
                continue
            if col.startswith('Cost_Category'):
                cost_category = rv
                continue
            if col.startswith('NARRATION'):
                rowop += f'<NARRATION>{rv}</NARRATION>\n'
                continue
            if col.startswith('Buyer_Name'):
                rowop += (f'<BASICBUYERNAME>{rv}</BASICBUYERNAME>\n'
                          f'<CONSIGNEEMAILINGNAME>{rv}</CONSIGNEEMAILINGNAME>\n'
                          f'<PARTYNAME>{rv}</PARTYNAME>\n'
                          f'<PARTYMAILINGNAME>{rv}</PARTYMAILINGNAME>\n')
                continue
            if col.startswith('Pincode'):
                if rv != 'emp':
                    rowop += f'<PARTYPINCODE>{rv}</PARTYPINCODE>\n<CONSIGNEEPINCODE>{rv}</CONSIGNEEPINCODE>\n'
                continue
            if col.startswith('State_Name'):
                if rv != 'emp':
                    rowop += (f'<STATENAME>{rv}</STATENAME>\n'
                              f'<BILLTOPLACE>{rv}</BILLTOPLACE>\n'
                              f'<CONSIGNEESTATENAME>{rv}</CONSIGNEESTATENAME>\n')
                continue
            if col.startswith('Address_1'):
                line1 = '' if rv == 'emp' else rv
                continue
            if col.startswith('Address_2'):
                line2 = '' if rv == 'emp' else rv
                continue
            if col.startswith('Address_3'):
                line3 = '' if rv == 'emp' else rv
                continue
            if col.startswith('Address_4'):
                line4 = '' if rv == 'emp' else rv
                rowop += _address_block(line1, line2, line3, line4)
                continue
            if col.startswith('POS'):
                rowop += f'<PLACEOFSUPPLY>{rv}</PLACEOFSUPPLY>\n<SHIPTOPLACE>{rv}</SHIPTOPLACE>\n'
                continue
            if col.startswith('Country'):
                rowop += f'<COUNTRYOFRESIDENCE>{rv}</COUNTRYOFRESIDENCE>'
                continue
            if col.startswith('Registration_Type'):
                continue
            if col.startswith('Company_GSTIN'):
                if rv != 'emp':
                    rowop += f'<PARTYGSTIN>{rv}</PARTYGSTIN>\n<CONSIGNEEGSTIN>{rv}</CONSIGNEEGSTIN>\n'
                continue
            if col.startswith('DebitLedger'):
                if rv != 'emp':
                    rowop += (f'<PARTYLEDGERNAME>{rv}</PARTYLEDGERNAME>\n'
                              f'<LEDGERENTRIES.LIST>\n<LEDGERNAME>{rv}</LEDGERNAME>\n')
                continue
            if col.startswith('AmountDebit'):
                if rv != 'emp':
                    rowop += (f'<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>\n'
                              f'<ISPARTYLEDGER>Yes</ISPARTYLEDGER>\n'
                              f'<AMOUNT>{rv}</AMOUNT>\n'
                              f'<BILLALLOCATIONS.LIST>\n<NAME>{inv_no}</NAME>\n'
                              f'<BILLTYPE>{inv_no}</BILLTYPE>\n'
                              f'<AMOUNT>{rv}</AMOUNT>\n'
                              f'</BILLALLOCATIONS.LIST>\n</LEDGERENTRIES.LIST>')
                continue

            # Generic ledger (revenue, GST)
            l_name = col
            if i == len(att) - 1 and rv == 'emp':
                rowop += '</VOUCHER>\n</TALLYMESSAGE>\n'
            if rv == 'emp':
                continue
            if not l_name.startswith(('CGST', 'IGST', 'SGST')):
                if col.startswith('Cost_Centre'):
                    continue
                nv = esc(str(df[att[i + 1]].iloc[j])) if i + 1 < len(att) else ''
                rowop += (f'<LEDGERENTRIES.LIST>\n<LEDGERNAME>{l_name}</LEDGERNAME>\n'
                          f'<GSTCLASS/>\n<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>\n'
                          f'<ISPARTYLEDGER>No</ISPARTYLEDGER>\n<AMOUNT>{rv}</AMOUNT>\n'
                          f'<CATEGORYALLOCATIONS.LIST>\n<CATEGORY>{cost_category}</CATEGORY>\n'
                          f'<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>\n'
                          f'<COSTCENTREALLOCATIONS.LIST>\n<NAME>{nv}</NAME>\n'
                          f'<AMOUNT>{rv}</AMOUNT>\n</COSTCENTREALLOCATIONS.LIST>\n'
                          f'</CATEGORYALLOCATIONS.LIST>\n</LEDGERENTRIES.LIST>\n')
            else:
                close = '\n</VOUCHER>\n</TALLYMESSAGE>\n' if i == len(att) - 1 else ''
                rowop += (f'<LEDGERENTRIES.LIST>\n<LEDGERNAME>{l_name}</LEDGERNAME>\n'
                          f'<GSTCLASS/>\n<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>\n'
                          f'<ISPARTYLEDGER>No</ISPARTYLEDGER>\n<AMOUNT>{rv}</AMOUNT>\n'
                          f'</LEDGERENTRIES.LIST>{close}\n')

        srop += (f'<TALLYMESSAGE xmlns:UDF="TallyUDF">\n'
                 f'<VOUCHER VCHTYPE="{v_type}" ACTION="Create" OBJVIEW="Accounting Voucher View">\n'
                 f'{rowop}')

    return HEADER + srop + FOOTER


def convert_sale_usd(df: pd.DataFrame) -> str:
    att = df.columns
    srop = ''
    for j in range(len(df)):
        rowop = ''
        v_type = inv_no = cost_category = country = ''
        line1 = line2 = line3 = line4 = ''
        currency_symbol = '$'
        currency_name = 'USD'
        e_rate = None

        for i in range(len(att)):
            col = att[i]
            rv = esc(str(df[col].iloc[j]))
            raw = str(df[col].iloc[j])

            if col.startswith('DATE'):
                rowop += f'<{col}>{rv}</{col}>\n<REFERENCEDATE>{rv}</REFERENCEDATE>\n'
                continue
            if col.startswith('VOUCHERTYPENAME'):
                v_type = rv
                rowop += (f'<VOUCHERTYPENAME>{rv}</VOUCHERTYPENAME>\n'
                          f'<VOUCHERTYPEORIGNAME>{rv}</VOUCHERTYPEORIGNAME>\n'
                          f'<VCHENTRYMODE>Accounting Invoice</VCHENTRYMODE>\n')
                continue
            if col.startswith('VOUCHERNUMBER'):
                rowop += f'<VOUCHERNUMBER>{rv}</VOUCHERNUMBER>\n'
                continue
            if col.startswith('Reference'):
                inv_no = rv
                rowop += f'<REFERENCE>{rv}</REFERENCE>\n'
                continue
            if col.startswith('Cost_Category'):
                if rv != 'emp':
                    cost_category = rv
                continue
            if col.startswith('NARRATION'):
                rowop += f'<NARRATION>{rv}</NARRATION>\n'
                continue
            if col.startswith('Buyer_Name'):
                rowop += (f'<BASICBUYERNAME>{rv}</BASICBUYERNAME>\n'
                          f'<CONSIGNEEMAILINGNAME>{rv}</CONSIGNEEMAILINGNAME>\n'
                          f'<PARTYNAME>{rv}</PARTYNAME>\n'
                          f'<PARTYMAILINGNAME>{rv}</PARTYMAILINGNAME>\n'
                          f'<BASICBASEPARTYNAME>{rv}</BASICBASEPARTYNAME>\n')
                continue
            if col.startswith('Pincode'):
                if rv != 'emp':
                    rowop += f'<PARTYPINCODE>{rv}</PARTYPINCODE>\n<CONSIGNEEPINCODE>{rv}</CONSIGNEEPINCODE>\n'
                continue
            if col.startswith('State_Name'):
                if rv != 'emp':
                    rowop += (f'<STATENAME>{rv}</STATENAME>\n'
                              f'<BILLTOPLACE>{rv}</BILLTOPLACE>\n'
                              f'<CONSIGNEESTATENAME>{rv}</CONSIGNEESTATENAME>\n')
                continue
            if col.startswith('Address_1'):
                line1 = '' if rv == 'emp' else rv
                continue
            if col.startswith('Address_2'):
                line2 = '' if rv == 'emp' else rv
                continue
            if col.startswith('Address_3'):
                line3 = '' if rv == 'emp' else rv
                continue
            if col.startswith('Address_4'):
                line4 = '' if rv == 'emp' else rv
                rowop += _address_block(line1, line2, line3, line4)
                continue
            if col.startswith('POS'):
                rowop += f'<PLACEOFSUPPLY>{rv}</PLACEOFSUPPLY>\n'
                continue
            if col.startswith('Registration_Type'):
                continue
            if col.startswith('Company_GSTIN'):
                if rv != 'emp':
                    rowop += f'<PARTYGSTIN>{rv}</PARTYGSTIN>\n<CONSIGNEEGSTIN>{rv}</CONSIGNEEGSTIN>\n'
                continue
            if col.startswith('EX_RATE'):
                if rv != 'emp':
                    e_rate = safe_float(raw.strip(), default=1.0)
                continue
            if col.startswith('Country'):
                country = rv
                rowop += (f'<COUNTRYOFRESIDENCE>{country}</COUNTRYOFRESIDENCE>\n'
                          f'<SHIPTOPLACE>{country}</SHIPTOPLACE>\n'
                          f'<BILLTOPLACE>{country}</BILLTOPLACE>\n'
                          f'<CONSIGNEECOUNTRYNAME>{country}</CONSIGNEECOUNTRYNAME>')
                continue
            if col.startswith('DebitLedger'):
                if rv != 'emp':
                    rowop += (f'<PARTYLEDGERNAME>{rv}</PARTYLEDGERNAME>\n'
                              f'<CURRENCYNAME>{currency_name}</CURRENCYNAME>\n'
                              f'<LEDGERENTRIES.LIST>\n<LEDGERNAME>{rv}</LEDGERNAME>\n')
                continue
            if col.startswith('AmountDebit'):
                if rv != 'emp':
                    amt, sym = parse_currency(raw)
                    if sym:
                        currency_symbol = sym
                        currency_name = CURRENCY_MAP.get(sym, currency_name)
                    rate = e_rate if e_rate is not None else 1.0
                    inr = round((amt or 0.0) * rate, 2)
                    tag = f'-{rv} @ ₹{rate}/{currency_symbol} = -₹{inr}'
                    rowop += (f'<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>\n'
                              f'<ISPARTYLEDGER>Yes</ISPARTYLEDGER>\n'
                              f'<AMOUNT>{tag}</AMOUNT>\n'
                              f'<BILLALLOCATIONS.LIST>\n<NAME>{inv_no}</NAME>\n'
                              f'<BILLTYPE>{inv_no}</BILLTYPE>\n'
                              f'<AMOUNT>{tag}</AMOUNT>\n'
                              f'</BILLALLOCATIONS.LIST>\n</LEDGERENTRIES.LIST>\n')
                continue

            # Generic ledger (revenue, GST)
            l_name = col
            if i == len(att) - 1 and rv == 'emp':
                rowop += '</VOUCHER>\n</TALLYMESSAGE>\n'
            if rv == 'emp':
                continue
            if not l_name.startswith(('CGST', 'IGST', 'SGST')):
                if col.startswith('Cost_Centre'):
                    continue
                amt, sym = parse_currency(raw)
                if sym:
                    currency_symbol = sym
                    currency_name = CURRENCY_MAP.get(sym, currency_name)
                rate = e_rate if e_rate is not None else 1.0
                inr = round((amt or 0.0) * rate, 2)
                nv = esc(str(df[att[i + 1]].iloc[j])) if i + 1 < len(att) else ''
                tag = f'{rv} @ ₹{rate}/{currency_symbol} = ₹{inr}'
                rowop += (f'<LEDGERENTRIES.LIST>\n<LEDGERNAME>{l_name}</LEDGERNAME>\n'
                          f'<GSTCLASS/>\n<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>\n'
                          f'<ISPARTYLEDGER>No</ISPARTYLEDGER>\n<AMOUNT>{tag}</AMOUNT>\n'
                          f'<CATEGORYALLOCATIONS.LIST>\n<CATEGORY>{cost_category}</CATEGORY>\n'
                          f'<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>\n'
                          f'<COSTCENTREALLOCATIONS.LIST>\n<NAME>{nv}</NAME>\n'
                          f'<AMOUNT>{inr}</AMOUNT>\n</COSTCENTREALLOCATIONS.LIST>\n'
                          f'</CATEGORYALLOCATIONS.LIST>\n</LEDGERENTRIES.LIST>\n')
            else:
                close = '\n</VOUCHER>\n</TALLYMESSAGE>\n' if i == len(att) - 1 else ''
                rowop += (f'<LEDGERENTRIES.LIST>\n<LEDGERNAME>{l_name}</LEDGERNAME>\n'
                          f'<GSTCLASS/>\n<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>\n'
                          f'<ISPARTYLEDGER>No</ISPARTYLEDGER>\n<AMOUNT>{rv}</AMOUNT>\n'
                          f'</LEDGERENTRIES.LIST>{close}\n')

        srop += (f'<TALLYMESSAGE xmlns:UDF="TallyUDF">\n'
                 f'<VOUCHER VCHTYPE="{v_type}" ACTION="Create" OBJVIEW="Accounting Voucher View">\n'
                 f'{rowop}')

    return HEADER + srop + FOOTER


# ---------- receipt ----------------------------------------------------------

RECEIPT_HEADER = (
    '<ENVELOPE>\n<HEADER>\n<TALLYREQUEST>Import Data</TALLYREQUEST>\n</HEADER>\n'
    '<BODY>\n<IMPORTDATA>\n<REQUESTDESC>\n<REPORTNAME>Vouchers</REPORTNAME>\n'
    '<STATICVARIABLES>\n'
    '<SVCURRENTCOMPANY>SHOPSENSE RETAIL TECHNOLOGIES LTD</SVCURRENTCOMPANY>\n'
    '</STATICVARIABLES>\n</REQUESTDESC>\n<REQUESTDATA>\n'
)


def _tally_date(raw) -> str:
    """Convert any date-like value → YYYYMMDD string for Tally."""
    try:
        return pd.to_datetime(str(int(float(str(raw)))), format='%Y%m%d').strftime('%Y%m%d')
    except Exception:
        return pd.to_datetime(str(raw)).strftime('%Y%m%d')


def _bq_client():
    """Return a BigQuery client, using GOOGLE_CREDENTIALS env var if set (Railway/cloud)."""
    from google.cloud import bigquery
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    if creds_json:
        import json
        from google.oauth2 import service_account
        info = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/bigquery.readonly']
        )
        return bigquery.Client(project='fynd-db', credentials=creds)
    return bigquery.Client(project='fynd-db')


def fetch_bq_receivables(invoice_nos: list[str] | None = None) -> dict:
    """Fetch {Vch_No: Debit} from BigQuery Trade Receivables table.

    If *invoice_nos* is provided, adds a WHERE IN filter for speed.
    Falls back to pulling the full primary_group filter otherwise.
    """
    from google.cloud import bigquery   # lazy import — only needed for BQ mode
    client = _bq_client()

    if invoice_nos:
        placeholders = ', '.join(f'"{v}"' for v in invoice_nos)
        query = f"""
            SELECT Vch_No, Debit
            FROM `fynd-db.Tally_23_24.voucher_transaction`
            WHERE primary_group = "Trade Receivables"
              AND Vch_No IN ({placeholders})
        """
    else:
        query = """
            SELECT Vch_No, Debit
            FROM `fynd-db.Tally_23_24.voucher_transaction`
            WHERE primary_group = "Trade Receivables"
        """

    df = client.query(query).to_dataframe()
    return df.set_index('Vch_No')['Debit'].to_dict()


def convert_receipt(df_pay: pd.DataFrame,
                    receivables_lookup: dict) -> tuple[str, list[dict]]:
    """Generate Receipt XML.

    Returns (xml_string, warnings) where warnings is a list of dicts for
    invoices that weren't found in the Trade Receivables lookup.
    """
    srop = ''
    warnings: list[dict] = []

    for idx, row in df_pay.iterrows():
        date     = _tally_date(row['DATE'])
        vtype    = esc(str(row.get('VOUCHERTYPENAME', 'Receipt')))
        vno      = esc(str(row.get('VOUCHERNUMBER', f'AUTO{idx+1}')))
        narr     = esc(str(row.get('NARRATION', 'Receipt against invoice')))
        bank     = esc(str(row['DebitLedger']))
        bank_amt = esc(str(row['AmountDebitLedger']))
        party    = esc(str(row['CreditLedger']))
        party_amt= esc(str(row['AmountCreditLedger']))
        tds_leg  = esc(str(row.get('TDSLedger', '')))
        tds_amt  = esc(str(row.get('AmountTDS', '0')))

        invoices = [i.strip() for i in str(row.get('Invoice', '')).split(',') if i.strip()]

        voucher = (
            f'<TALLYMESSAGE xmlns:UDF="TallyUDF">\n'
            f'<VOUCHER VCHTYPE="{vtype}" ACTION="Create" OBJVIEW="Accounting Voucher View">\n'
            f'<DATE>{date}</DATE>\n'
            f'<EFFECTIVEDATE>{date}</EFFECTIVEDATE>\n'
            f'<VOUCHERTYPENAME>{vtype}</VOUCHERTYPENAME>\n'
            f'<VOUCHERNUMBER>{vno}</VOUCHERNUMBER>\n'
            f'<NARRATION>{narr}</NARRATION>\n'
            f'<PARTYLEDGERNAME>{party}</PARTYLEDGERNAME>\n'
            f'<REMOVEZEROENTRIES>Yes</REMOVEZEROENTRIES>\n\n'
            f'<ALLLEDGERENTRIES.LIST>\n'
            f'<LEDGERNAME>{bank}</LEDGERNAME>\n'
            f'<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>\n'
            f'<ISPARTYLEDGER>No</ISPARTYLEDGER>\n'
            f'<AMOUNT>{bank_amt}</AMOUNT>\n'
            f'</ALLLEDGERENTRIES.LIST>\n\n'
            f'<ALLLEDGERENTRIES.LIST>\n'
            f'<LEDGERNAME>{party}</LEDGERNAME>\n'
            f'<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>\n'
            f'<ISPARTYLEDGER>Yes</ISPARTYLEDGER>\n'
            f'<AMOUNT>{party_amt}</AMOUNT>\n'
        )

        for inv in invoices:
            inv_amt = receivables_lookup.get(inv, 0.0)
            if inv_amt == 0.0:
                warnings.append({
                    'row':     idx + 2,
                    'invoice': inv,
                    'issue':   'Not found in Trade Receivables — amount set to 0',
                })
            voucher += (
                f'<BILLALLOCATIONS.LIST>\n'
                f'<NAME>{esc(inv)}</NAME>\n'
                f'<BILLTYPE>Agst Ref</BILLTYPE>\n'
                f'<AMOUNT>{esc(str(inv_amt))}</AMOUNT>\n'
                f'</BILLALLOCATIONS.LIST>\n'
            )

        voucher += '</ALLLEDGERENTRIES.LIST>\n'

        if tds_leg.lower() not in ('', 'emp', 'nan'):
            voucher += (
                f'<ALLLEDGERENTRIES.LIST>\n'
                f'<LEDGERNAME>{tds_leg}</LEDGERNAME>\n'
                f'<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>\n'
                f'<ISPARTYLEDGER>No</ISPARTYLEDGER>\n'
                f'<AMOUNT>{tds_amt}</AMOUNT>\n'
                f'</ALLLEDGERENTRIES.LIST>\n'
            )

        voucher += '</VOUCHER>\n</TALLYMESSAGE>\n'
        srop += voucher

    return RECEIPT_HEADER + srop + FOOTER, warnings


# ---------- nexus billing ----------------------------------------------------
# Nexus generates TWO XMLs from one CSV:
#   1. Sale XML  (VAR-INV)  — identical logic to convert_sale
#   2. JV XML    (S-JV)     — auto-detects COD/PPD from NARRATION

def convert_nexus_sale(df: pd.DataFrame) -> str:
    """Sale (VAR-INV) XML for Nexus Billing — same structure as convert_sale."""
    return convert_sale(df)


def convert_nexus_jv(df: pd.DataFrame) -> str:
    """Journal Voucher (S-JV) XML for Nexus Billing.

    For each invoice row the JV:
      - Detects COD or PPD from the NARRATION column
      - DEBIT  leg: DebitLedger with '_C' → '_Nexus_COD_V' / '_Nexus_PPD_V'
      - CREDIT leg: DebitLedger unchanged
      - Amount: abs(AmountDebitLedger)
    """
    srop = ''
    narr_col = next((c for c in df.columns
                     if c.upper().startswith('NARRATION')), 'NARRATION')
    amt_col = next((c for c in df.columns
                    if c.startswith('AmountDebit')), 'AmountDebitLedger')
    deb_col = next((c for c in df.columns
                    if c.startswith('DebitLedger')), 'DebitLedger')

    for j in range(len(df)):
        date_val   = esc(str(df['DATE'].iloc[j]))
        inv_no     = esc(str(df['VOUCHERNUMBER'].iloc[j]))
        narration  = str(df[narr_col].iloc[j])
        base_ledger = esc(str(df[deb_col].iloc[j]))

        mode   = 'PPD' if 'PPD' in narration.upper() else 'COD'
        suffix = '_Nexus_PPD_V' if mode == 'PPD' else '_Nexus_COD_V'
        debit_ledger = (base_ledger[:-2] + suffix
                        if base_ledger.endswith('_C')
                        else base_ledger + suffix)

        raw_amt   = float(str(df[amt_col].iloc[j]))
        debit_amt = -abs(raw_amt)
        credit_amt = abs(raw_amt)
        narr_text = esc(
            f'Being Transfer entry passed against INV No.: {inv_no}'
            f' for Nexus storefront - {mode}'
        )

        srop += (
            f'<TALLYMESSAGE xmlns:UDF="TallyUDF">\n'
            f'<VOUCHER VCHTYPE="S-JV" ACTION="Create" OBJVIEW="Accounting Voucher View">\n'
            f'<DATE>{date_val}</DATE>\n'
            f'<PARTYLEDGERNAME>{base_ledger}</PARTYLEDGERNAME>\n'
            f'<VOUCHERTYPENAME>S-JV</VOUCHERTYPENAME>\n'
            f'<REFERENCE>On Account</REFERENCE>\n'
            f'<Narration>{narr_text}</Narration>\n'
            f'<ALLLEDGERENTRIES.LIST>\n'
            f'<LEDGERNAME>{debit_ledger}</LEDGERNAME>\n'
            f'<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>\n'
            f'<AMOUNT>{debit_amt}</AMOUNT>\n'
            f'</ALLLEDGERENTRIES.LIST>\n'
            f'<ALLLEDGERENTRIES.LIST>\n'
            f'<LEDGERNAME>{base_ledger}</LEDGERNAME>\n'
            f'<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>\n'
            f'<AMOUNT>{credit_amt}</AMOUNT>\n'
            f'</ALLLEDGERENTRIES.LIST>\n'
            f'</VOUCHER>\n</TALLYMESSAGE>\n'
        )

    return HEADER + srop + FOOTER


# ---------- routes -----------------------------------------------------------

CONVERTERS = {
    'cn':       convert_cn,
    'jv':       convert_jv,
    'sale':     convert_sale,
    'sale_usd': convert_sale_usd,
}


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/bq-status')
def bq_status():
    """Check whether BigQuery credentials are valid by running a cheap test query."""
    try:
        client = _bq_client()
        list(client.query('SELECT 1').result())
        return jsonify({'available': True, 'project': 'fynd-db'})
    except Exception as e:
        return jsonify({'available': False, 'reason': str(e)})


@app.route('/process', methods=['POST'])
def process():
    doc_type = request.form.get('type', 'sale')
    filename = request.form.get('filename', 'output')
    file = request.files.get('file')

    if not file:
        return jsonify({'error': 'No file uploaded'}), 400
    all_types = {**CONVERTERS, 'nexus': None, 'receipt': None}
    if doc_type not in all_types:
        return jsonify({'error': f'Unknown type: {doc_type}'}), 400

    try:
        content = file.read()
        # Try utf-8-sig first (strips BOM); fall back to latin-1 for older files
        try:
            df = pd.read_csv(io.BytesIO(content), encoding='utf-8-sig')
        except Exception:
            df = pd.read_csv(io.BytesIO(content), encoding='latin-1')
        df.columns = [c.lstrip('﻿').strip() for c in df.columns]
    except Exception as e:
        return jsonify({'error': f'Failed to read CSV: {e}'}), 400

    validation = validate(df, doc_type)

    try:
        import traceback
        if doc_type == 'receipt':
            bq_mode = request.form.get('bq_mode') == 'true'
            if bq_mode:
                # Extract all invoice numbers from the receipt CSV so we can run
                # a targeted BQ query instead of pulling all Trade Receivables.
                all_invoices = []
                inv_col = next((c for c in df.columns if c == 'Invoice'), None)
                if inv_col:
                    for val in df[inv_col]:
                        all_invoices += [i.strip() for i in str(val).split(',') if i.strip()]
                try:
                    receivables_lookup = fetch_bq_receivables(all_invoices or None)
                    validation['bq_rows_fetched'] = len(receivables_lookup)
                except ImportError:
                    return jsonify({'error':
                        'google-cloud-bigquery not installed.\n'
                        'Run: pip install google-cloud-bigquery'}), 400
                except Exception as e:
                    return jsonify({'error': f'BigQuery error: {e}'}), 400
            else:
                tr_file = request.files.get('tr_file')
                if not tr_file:
                    return jsonify({'error': 'Please upload the Trade Receivables CSV '
                                             '(or switch to BigQuery mode)'}), 400
                try:
                    tr_bytes = tr_file.read()
                    df_tr = pd.read_csv(io.BytesIO(tr_bytes), encoding='utf-8-sig')
                    df_tr.columns = [c.lstrip('﻿').strip() for c in df_tr.columns]
                    receivables_lookup = df_tr.set_index('Vch_No')['Debit'].to_dict()
                    validation['bq_rows_fetched'] = None  # not from BQ
                except Exception as e:
                    return jsonify({'error': f'Failed to read Trade Receivables CSV: {e}'}), 400

            xml_content, receipt_warnings = convert_receipt(df, receivables_lookup)
            validation['receipt_warnings'] = receipt_warnings
            # Count total invoices processed
            inv_col = next((c for c in df.columns if c == 'Invoice'), None)
            validation['total_invoices'] = sum(
                len([i for i in str(v).split(',') if i.strip()])
                for v in (df[inv_col] if inv_col else [])
            )
            token = str(uuid.uuid4())
            xml_store[token] = (xml_content, os.path.splitext(filename)[0] + '_TALLY.xml')
            validation['token']    = token
            validation['is_nexus'] = False

        elif doc_type == 'nexus':
            xml_sale = convert_nexus_sale(df)
            xml_jv   = convert_nexus_jv(df)
            base = os.path.splitext(filename)[0]
            t_sale = str(uuid.uuid4())
            t_jv   = str(uuid.uuid4())
            xml_store[t_sale] = (xml_sale, base + '_sale.xml')
            xml_store[t_jv]   = (xml_jv,   base + '_jv.xml')
            validation['token_sale'] = t_sale
            validation['token_jv']   = t_jv
            validation['is_nexus']   = True
        else:
            xml_content = CONVERTERS[doc_type](df)
            token = str(uuid.uuid4())
            xml_store[token] = (xml_content, os.path.splitext(filename)[0] + '.xml')
            validation['token'] = token
            validation['is_nexus'] = False
    except Exception as e:
        tb = traceback.format_exc()
        return jsonify({'error': f'Conversion error: {e}', 'detail': tb,
                        'validation': validation}), 400

    # Trim old tokens (keep max 30)
    while len(xml_store) > 30:
        del xml_store[next(iter(xml_store))]

    return jsonify({'ok': True, 'validation': validation})


@app.route('/download/<token>')
def download(token):
    entry = xml_store.get(token)
    if not entry:
        return 'File not found or expired', 404
    xml_content, out_name = entry
    buf = io.BytesIO(xml_content.encode('utf-8'))
    return send_file(buf, mimetype='application/xml',
                     as_attachment=True, download_name=out_name)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    print(f'\n  Tally XML Dashboard running at: http://localhost:{port}\n')
    app.run(debug=False, host='0.0.0.0', port=port)
