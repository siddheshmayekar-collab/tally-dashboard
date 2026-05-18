import os
import sys

# Check if pandas is installed
try:
    import pandas as pd
except ModuleNotFoundError:
    print("Error: 'pandas' module is not installed. Please install it using pip or conda.")
    sys.exit(1)

# XML envelope parts
header = (
    '<ENVELOPE>\n<HEADER>\n<TALLYREQUEST>Import Data</TALLYREQUEST>\n</HEADER>\n'
    '<BODY>\n<IMPORTDATA>\n<REQUESTDESC>\n<REPORTNAME>All Masters</REPORTNAME>\n'
    '</REQUESTDESC>\n<REQUESTDATA>\n'
)
footer = '</REQUESTDATA>\n</IMPORTDATA>\n</BODY>\n</ENVELOPE>\n'

# Function to escape XML characters
def escape_xml_chars(value):
    return (
        value.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace("'", "&apos;")
             .replace('"', "&quot;")
    )

# Main conversion function
def journal_vouchers(inputfile):
    if not inputfile.lower().endswith('.csv'):
        print('Expected a CSV file')
        return

    outputfile = os.path.splitext(inputfile)[0] + '.xml'

    try:
        df = pd.read_csv(inputfile)
    except FileNotFoundError:
        print(f'CSV file not found: {inputfile}')
        return

    columns = df.columns
    final_xml_body = ''

    for row_idx in range(len(df)):
        row_data = ''
        for col_idx in range(len(columns)):
            col_name = columns[col_idx]
            value = str(df[col_name][row_idx]).strip()

            if value.lower() == 'emp':
                continue

            value = escape_xml_chars(value)

            if col_name.startswith(('entry_code', 'Mode')):
                continue

            if col_name.startswith('VOUCHERTYPENAME'):
                v_type = value
                party_name = escape_xml_chars(str(df[columns[col_idx + 4]][row_idx]))
                row_data += (
                    f'<PARTYLEDGERNAME>{party_name}</PARTYLEDGERNAME>\n'
                    f'<{col_name}>{value}</{col_name}>\n'
                    '<REFERENCE>On Account</REFERENCE>\n'
                )
                continue

            if col_name.startswith('DebitLedger'):
                row_data += f'<ALLLEDGERENTRIES.LIST>\n<LEDGERNAME>{value}</LEDGERNAME>\n'
                continue

            if col_name.startswith('AmountDebit'):
                row_data += (
                    f'<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>\n'
                    f'<AMOUNT>{value}</AMOUNT>\n</ALLLEDGERENTRIES.LIST>\n'
                )
                continue

            if col_name.startswith('CreditLedger'):
                row_data += f'<ALLLEDGERENTRIES.LIST>\n<LEDGERNAME>{value}</LEDGERNAME>\n'
                continue

            if col_name.startswith('AmountCredit'):
                row_data += (
                    f'<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>\n'
                    f'<AMOUNT>{value}</AMOUNT>\n</ALLLEDGERENTRIES.LIST>\n'
                )
                if col_idx == len(columns) - 1:
                    row_data += '</VOUCHER>\n</TALLYMESSAGE>\n'
                continue

            if col_name.startswith('DATE'):
                row_data += f'<{col_name}>{value}</{col_name}>\n'
                continue

            # Default tag for other fields
            row_data += f'<{col_name}>{value}</{col_name}>\n'

        final_xml_body += (
            '<TALLYMESSAGE xmlns:UDF="TallyUDF">\n'
            f'<VOUCHER VCHTYPE="{v_type}" ACTION="Create" OBJVIEW="Accounting Voucher View">\n'
            f'{row_data}'
        )

    # Write to XML
    full_output = header + final_xml_body + footer
    with open(outputfile, 'w+', encoding='utf-8') as f:
        f.write(full_output)

    print(f"✅ XML file created: {outputfile}")

# Only run if script is executed directly
if __name__ == '__main__':
    journal_vouchers('jv.csv')
