import pandas as pd
import os

# XML envelope headers
header = '''<ENVELOPE>
<HEADER>
<TALLYREQUEST>Import Data</TALLYREQUEST>
</HEADER>
<BODY>
<IMPORTDATA>
<REQUESTDESC>
<REPORTNAME>Vouchers</REPORTNAME>
<STATICVARIABLES>
<SVCURRENTCOMPANY>SHOPSENSE RETAIL TECHNOLOGIES LTD</SVCURRENTCOMPANY>
</STATICVARIABLES>
</REQUESTDESC>
<REQUESTDATA>
'''

footer = '''</REQUESTDATA>
</IMPORTDATA>
</BODY>
</ENVELOPE>
'''

# Escapes characters for XML
def sanitize_xml(text):
    text = str(text)
    return (
        text.replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace("'", '&apos;')
            .replace('"', '&quot;')
    )

def generate_xml_with_trade_receivables(payment_csv_file, receivables_csv_file):
    try:
        # Read the Trade Receivables data
        df_receivables = pd.read_csv(receivables_csv_file)
        # Create a lookup dictionary: {Vch_No: Debit amount}
        receivables_lookup = df_receivables.set_index('Vch_No')['Debit'].to_dict()

        # Read the payment data
        df_payment = pd.read_csv(payment_csv_file)
        
        output_file = os.path.splitext(payment_csv_file)[0] + '_FINAL_TALLY_TRADE_REC.xml'
        srop = ''

        for index, row in df_payment.iterrows():
            # Clean and assign variables
            date = str(row['DATE'])
            vtype = sanitize_xml(row['VOUCHERTYPENAME'])
            vno = sanitize_xml(str(row.get('VOUCHERNUMBER', f"AUTO{index+1}")))
            narration = sanitize_xml(str(row.get('NARRATION', 'Receipt against invoice')))
            bank = sanitize_xml(str(row['DebitLedger']))
            bank_amt = sanitize_xml(str(row['AmountDebitLedger']))
            party = sanitize_xml(str(row['CreditLedger']))
            party_amt_total = sanitize_xml(str(row['AmountCreditLedger']))
            tds_ledger = sanitize_xml(str(row.get('TDSLedger', '')))
            tds_amt = sanitize_xml(str(row.get('AmountTDS', '0')))
            
            # Handle multiple invoices from the 'Invoice' column
            invoices = str(row.get('Invoice', '')).split(',')
            invoices = [inv.strip() for inv in invoices if inv.strip()]

            # XML Voucher
            voucher = f'''<TALLYMESSAGE xmlns:UDF="TallyUDF">
<VOUCHER VCHTYPE="{vtype}" ACTION="Create" OBJVIEW="Accounting Voucher View">
<DATE>{date}</DATE>
<VOUCHERTYPENAME>{vtype}</VOUCHERTYPENAME>
<VOUCHERNUMBER>{vno}</VOUCHERNUMBER>
<NARRATION>{narration}</NARRATION>
<PARTYLEDGERNAME>{party}</PARTYLEDGERNAME>
<REMOVEZEROENTRIES>Yes</REMOVEZEROENTRIES>

<ALLLEDGERENTRIES.LIST>
<LEDGERNAME>{bank}</LEDGERNAME>
<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
<ISPARTYLEDGER>No</ISPARTYLEDGER>
<AMOUNT>{bank_amt}</AMOUNT>
</ALLLEDGERENTRIES.LIST>

<ALLLEDGERENTRIES.LIST>
<LEDGERNAME>{party}</LEDGERNAME>
<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
<ISPARTYLEDGER>Yes</ISPARTYLEDGER>
<AMOUNT>{party_amt_total}</AMOUNT>
'''
            # Add a BILLALLOCATIONS.LIST block for each invoice, looking up the amount
            for invoice in invoices:
                invoice_amt = receivables_lookup.get(invoice, 0.00)
                if invoice_amt == 0.00:
                    print(f"Warning: Invoice '{invoice}' not found in Trade Receivables. Amount set to 0.")
                
                voucher += f'''<BILLALLOCATIONS.LIST>
<NAME>{sanitize_xml(invoice)}</NAME>
<BILLTYPE>Agst Ref</BILLTYPE>
<AMOUNT>{sanitize_xml(str(invoice_amt))}</AMOUNT>
</BILLALLOCATIONS.LIST>
'''
            voucher += '</ALLLEDGERENTRIES.LIST>\n'

            # Add TDS ledger entry if present
            if tds_ledger.lower() != 'emp' and tds_ledger.strip() != '':
                voucher += f'''<ALLLEDGERENTRIES.LIST>
<LEDGERNAME>{tds_ledger}</LEDGERNAME>
<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
<ISPARTYLEDGER>No</ISPARTYLEDGER>
<AMOUNT>{tds_amt}</AMOUNT>
</ALLLEDGERENTRIES.LIST>
'''
            voucher += '</VOUCHER>\n</TALLYMESSAGE>\n'
            srop += voucher

        final_xml = header + srop + footer

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(final_xml)

        print(f"✅ XML file generated: {output_file}")
        return output_file
    
    except Exception as e:
        print(f"An error occurred: {e}")
        return None

# Call the function with your CSV files
generate_xml_with_trade_receivables("receipt.csv", "Trade Receivables.csv")
