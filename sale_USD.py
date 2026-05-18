import pandas as pd
import os
import re

header = '<ENVELOPE>\n<HEADER>\n<TALLYREQUEST>Import Data</TALLYREQUEST>\n</HEADER>\n<BODY>\n<IMPORTDATA>\n<REQUESTDESC>\n<REPORTNAME>All Masters</REPORTNAME>\n</REQUESTDESC>\n<REQUESTDATA>\n'
footer ='</REQUESTDATA>\n</IMPORTDATA>\n</BODY>\n</ENVELOPE>\n'

# --- helpers ---------------------------------------------------------------

CURRENCY_FROM_SYMBOL = {
    'RM': 'MYR',
    '$' : 'USD',
    '₹' : 'INR',
}

def parse_amount(raw: str):
    """
    Returns (value: float, symbol: str) given strings like:
    'RM558000', 'RM 558,000.50', '$1,234', '₹ 1,000', '(RM500.25)'
    """
    s = str(raw or '').strip()
    if s == '' or s.lower() == 'emp':
        return None, ''

    # detect negatives shown with parentheses
    neg = s.startswith('(') and s.endswith(')')
    if neg:
        s = s[1:-1].strip()

    # detect leading symbol
    symbol = ''
    for pref in ('RM', '$', '₹'):
        if s.startswith(pref):
            symbol = pref
            s = s[len(pref):].strip()
            break

    # remove thousands separators and any stray non-numeric chars
    s = s.replace(',', '')
    s = re.sub(r'[^0-9.\-]', '', s)

    if s == '' or s == '.':
        return None, symbol

    val = float(s)
    if neg:
        val = -val
    return val, symbol

def safe_float(x, default=None):
    try:
        return float(x)
    except Exception:
        return default

# --- main ------------------------------------------------------------------

def CSVtoXML(inputfile):
    passs = True
    print(inputfile)
    if not inputfile.lower().endswith('.csv'):
        print('Expected A CSV File')
        return 0
    outputfile = os.path.splitext(inputfile)[0] +'.xml'
    try:
        df=pd.read_csv(inputfile)
    except FileNotFoundError:
        print('CSV file not found')
        return 0

    att=df.columns
    rowop=''
    srop =''
    print('--->',att,'\n', len(att),len(df))
    for j in range(0,len(df)):
        rowop = ''
        passs = True

        # default per-row state
        currency_symbol = '$'   # default like old behavior
        currency_name   = 'USD' # will be switched to MYR if we see RM
        e_rate = None           # EX_RATE for this row
        cost_category = ''
        v_type = v_no = inv_no = ''
        b_name = ''
        line1 = line2 = line3 = line4 = ''
        country = ''

        for i in range(0,len(att)):
            row_value = str(df[att[i]][j])

            # XML escapes
            row_value = (row_value
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace("'", '&apos;')
                .replace('"', '&quot;')
            )

            if att[i].startswith('DATE'):
                date = row_value
                rowop+=f'<{att[i]}>{row_value}</{att[i]}>\n<REFERENCEDATE>{row_value}</REFERENCEDATE>\n'
                continue

            if att[i].startswith('VOUCHERTYPENAME'):
                v_type = row_value
                rowop+=f'<VOUCHERTYPENAME>{row_value}</VOUCHERTYPENAME>\n<VOUCHERTYPEORIGNAME>{row_value}</VOUCHERTYPEORIGNAME>\n<VCHENTRYMODE>Accounting Invoice</VCHENTRYMODE>\n'
                continue

            if att[i].startswith('VOUCHERNUMBER'):
                v_no = row_value
                rowop+=f'<VOUCHERNUMBER>{row_value}</VOUCHERNUMBER>\n'
                continue

            if att[i].startswith('Reference'):
                inv_no = row_value
                rowop+=f'<REFERENCE>{row_value}</REFERENCE>\n'
                continue

            if att[i].startswith('Cost_Category'):
                if row_value != 'emp':
                    cost_category = row_value
                continue

            if att[i].startswith('NARRATION'):
                rowop+=f'<NARRATION>{row_value}</NARRATION>\n'
                continue

            if att[i].startswith('Buyer_Name'):
                b_name = row_value
                rowop+=(
                    f'<BASICBUYERNAME>{row_value}</BASICBUYERNAME>\n'
                    f'<CONSIGNEEMAILINGNAME>{b_name}</CONSIGNEEMAILINGNAME>\n'
                    f'<PARTYNAME>{row_value}</PARTYNAME>\n'
                    f'<PARTYMAILINGNAME>{row_value}</PARTYMAILINGNAME>\n'
                    f'<BASICBASEPARTYNAME>{row_value}</BASICBASEPARTYNAME>\n'
                )
                continue

            if att[i].startswith('Pincode'):
                if row_value != 'emp':
                    rowop+=f'<PARTYPINCODE>{row_value}</PARTYPINCODE>\n<CONSIGNEEPINCODE>{row_value}</CONSIGNEEPINCODE>\n'
                continue

            if att[i].startswith('State_Name'):
                if row_value != 'emp':
                    rowop+=f'<STATENAME>{row_value}</STATENAME>\n<BILLTOPLACE>{row_value}</BILLTOPLACE>\n<CONSIGNEESTATENAME>{row_value}</CONSIGNEESTATENAME>\n'
                continue

            if att[i].startswith('Address_1'):
                line1 = '' if row_value=='emp' else row_value; continue
            if att[i].startswith('Address_2'):
                line2 = '' if row_value=='emp' else row_value; continue
            if att[i].startswith('Address_3'):
                line3 = '' if row_value=='emp' else row_value; continue
            if att[i].startswith('Address_4'):
                line4 = '' if row_value=='emp' else row_value
                rowop+=(
                    '<ADDRESS.LIST TYPE="String">\n'
                    f'<ADDRESS>{line1}</ADDRESS>\n<ADDRESS>{line2}</ADDRESS>\n'
                    f'<ADDRESS>{line3}</ADDRESS>\n<ADDRESS>{line4}</ADDRESS>\n'
                    '</ADDRESS.LIST>\n'
                    '<BASICBUYERADDRESS.LIST TYPE="String">\n'
                    f'<BASICBUYERADDRESS>{line1}</BASICBUYERADDRESS>\n'
                    f'<BASICBUYERADDRESS>{line2}</BASICBUYERADDRESS>\n'
                    f'<BASICBUYERADDRESS>{line3}</BASICBUYERADDRESS>\n'
                    f'<BASICBUYERADDRESS>{line4}</BASICBUYERADDRESS>\n'
                    '</BASICBUYERADDRESS.LIST>\n'
                )
                continue

            if att[i].startswith('POS'):
                rowop+=f'<PLACEOFSUPPLY>{row_value}</PLACEOFSUPPLY>\n'
                continue

            if att[i].startswith('Registration_Type'):
                continue

            if att[i].startswith('Company_GSTIN'):
                if row_value != 'emp':
                    rowop+=f'<PARTYGSTIN>{row_value}</PARTYGSTIN>\n<CONSIGNEEGSTIN>{row_value}</CONSIGNEEGSTIN>\n'
                continue

            if att[i].startswith('EX_RATE'):
                if row_value != 'emp':
                    e_rate = safe_float(row_value, default=1.0)
                continue

            if att[i].startswith('Country'):
                country = row_value
                rowop+=f'<COUNTRYOFRESIDENCE>{country}</COUNTRYOFRESIDENCE>\n<SHIPTOPLACE>{country}</SHIPTOPLACE>\n<BILLTOPLACE>{country}</BILLTOPLACE>\n<CONSIGNEECOUNTRYNAME>{country}</CONSIGNEECOUNTRYNAME>'
                continue

            if att[i].startswith('DebitLedger'):
                if row_value == 'emp':
                    continue
                # Set currency on first amount field later; for now write the tag
                rowop+=f'<PARTYLEDGERNAME>{row_value}</PARTYLEDGERNAME>\n<CURRENCYNAME>{currency_name}</CURRENCYNAME>\n<LEDGERENTRIES.LIST>\n<LEDGERNAME>{row_value}</LEDGERNAME>\n'
                continue

            if att[i].startswith('AmountDebit'):
                if row_value == 'emp':
                    continue
                amt, sym = parse_amount(row_value)
                if sym:
                    currency_symbol = sym
                    currency_name = CURRENCY_FROM_SYMBOL.get(sym, currency_name)
                # update conversion
                rate = e_rate if e_rate is not None else 1.0
                amount_debit = (amt or 0.0) * float(rate)
                rowop+=(
                    '<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>\n'
                    '<ISPARTYLEDGER>Yes</ISPARTYLEDGER>\n'
                    f'<AMOUNT>-{row_value} @ ₹{rate}/{currency_symbol if currency_symbol else ""} = -₹{round(amount_debit,2)}</AMOUNT>\n'
                    '<BILLALLOCATIONS.LIST>\n'
                    f'<NAME>{inv_no}</NAME>\n'
                    f'<BILLTYPE>{inv_no}</BILLTYPE>\n'
                    f'<AMOUNT>-{row_value} @ ₹{rate}/{currency_symbol if currency_symbol else ""} = -₹{round(amount_debit,2)}</AMOUNT>\n'
                    '</BILLALLOCATIONS.LIST>\n'
                    '</LEDGERENTRIES.LIST>\n'
                )
                continue

            # --- generic ledger lines (items / revenue / cost centres etc.) ---
            l_name = att[i]
            if i == len(att)-1 and row_value == 'emp':
                rowop+=f'</VOUCHER>\n</TALLYMESSAGE>\n'
                continue
            if row_value == 'emp':
                continue

            if not l_name.startswith(("CGST", "IGST", "SGST")):
                if att[i].startswith('Cost_Centre'):
                    continue
                # amount -> INR via EX_RATE
                amt, sym = parse_amount(row_value)
                if sym:
                    currency_symbol = sym
                    currency_name = CURRENCY_FROM_SYMBOL.get(sym, currency_name)
                rate = e_rate if e_rate is not None else 1.0
                INR = (amt or 0.0) * float(rate)
                rowop += f"""
                <LEDGERENTRIES.LIST>
                    <LEDGERNAME>{l_name}</LEDGERNAME>
                    <GSTCLASS/>
                    <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                    <ISPARTYLEDGER>No</ISPARTYLEDGER>
                    <AMOUNT>{row_value} @ ₹{rate}/{currency_symbol if currency_symbol else ""} = ₹{round(INR,2)}</AMOUNT>
                    <CATEGORYALLOCATIONS.LIST>
                        <CATEGORY>{cost_category}</CATEGORY>
                        <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                        <COSTCENTREALLOCATIONS.LIST>
                            <NAME>{df[att[i+1]][j]}</NAME>
                            <AMOUNT>{round(INR,2)}</AMOUNT>
                        </COSTCENTREALLOCATIONS.LIST>
                    </CATEGORYALLOCATIONS.LIST>
                </LEDGERENTRIES.LIST>
                """
            else:
                # GST ledgers are already INR values in your CSV, keep as-is
                if i != len(att)-1:
                    rowop += f"""
                    <LEDGERENTRIES.LIST>
                        <LEDGERNAME>{l_name}</LEDGERNAME>
                        <GSTCLASS/>
                        <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>No</ISPARTYLEDGER>
                        <AMOUNT>{row_value}</AMOUNT>
                    </LEDGERENTRIES.LIST>
                    """
                else:
                    rowop += f"""
                    <LEDGERENTRIES.LIST>
                        <LEDGERNAME>{l_name}</LEDGERNAME>
                        <GSTCLASS/>
                        <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>No</ISPARTYLEDGER>
                        <AMOUNT>{row_value}</AMOUNT>
                    </LEDGERENTRIES.LIST>\n</VOUCHER>\n</TALLYMESSAGE>\n
                    """

        # ensure the currency tag earlier reflects any RM we saw
        srop += f'<TALLYMESSAGE xmlns:UDF="TallyUDF">\n<VOUCHER VCHTYPE="{v_type}" ACTION="Create" OBJVIEW="Accounting Voucher View">\n' + rowop

    entireop=header+srop+footer
    with open(outputfile,'w+', encoding='utf-8') as f:
        f.write(entireop)

CSVtoXML('sale_USD.csv')
