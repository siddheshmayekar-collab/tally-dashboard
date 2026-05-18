import pandas as pd
import os

header = '<ENVELOPE>\n<HEADER>\n<TALLYREQUEST>Import Data</TALLYREQUEST>\n</HEADER>\n<BODY>\n<IMPORTDATA>\n<REQUESTDESC>\n<REPORTNAME>All Masters</REPORTNAME>\n</REQUESTDESC>\n<REQUESTDATA>\n'

footer ='</REQUESTDATA>\n</IMPORTDATA>\n</BODY>\n</ENVELOPE>\n'



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
    # print('--->',att,'\n', len(att),len(df))
    for j in range(0,len(df)):
        rowop = ''
        passs = True
        for i in range(0,len(att)):
            row_value = str(df[att[i]][j])
            if '&' in row_value:
                row_value = row_value.replace('&', '&amp;', row_value.count('&'))
            if '<' in row_value:
                row_value = row_value.replace('<', '&lt;', row_value.count('<'))
            if '>' in row_value:
                row_value = row_value.replace('>', '&gt;', row_value.count('>'))
            if "'" in row_value:
                row_value = row_value.replace("'", '&apos;', row_value.count("'"))
            if '"' in row_value:
                row_value = row_value.replace('"', '&quot;', row_value.count('"'))

            if att[i].startswith('DATE'):
                date = row_value
                rowop=rowop+f'<{att[i]}>{row_value}</{att[i]}>\n<REFERENCEDATE>{row_value}</REFERENCEDATE>\n'
                continue

            if att[i].startswith('VOUCHERTYPENAME'):
                v_type = row_value
                rowop=rowop+f'<VOUCHERTYPENAME>{row_value}</VOUCHERTYPENAME>\n<VOUCHERTYPEORIGNAME>{row_value}</VOUCHERTYPEORIGNAME>\n<VCHENTRYMODE>Accounting Invoice</VCHENTRYMODE>\n'
                continue

            if att[i].startswith('VOUCHERNUMBER'):
                v_no = row_value
                #print('Hellooooooooo VNO',v_no)
                rowop=rowop+f'<VOUCHERNUMBER>{row_value}</VOUCHERNUMBER>\n'
                continue

            if att[i].startswith('Reference'):
                inv_no = row_value
                #print('Hellooooooooo',inv_no)
                rowop=rowop+f'<REFERENCE>{row_value}</REFERENCE>\n'
                continue

            if att[i].startswith('Cost_Category'):
                cost_category = row_value
                # rowop=rowop+f'<CATEGORYALLOCATIONS.LIST>\n <CATEGORY>{df[att[i]][j]}</CATEGORY>\n<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>\n</CATEGORYALLOCATIONS.LIST>\n'
                continue

            # if att[i].startswith('Cost_Centre'):
            #     cost_centre = row_value
            #     print('cost_centre' , cost_centre ,row_value ,type(row_value))
            #     rowop=rowop+f'<COSTCENTRENAME="Tnx_StoreOS_CI">\n<NAME>{df[att[i]][j]}</CATEGORY>\n<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>\n</CATEGORYALLOCATIONS.LIST>\n'
            #     continue

            if att[i].startswith('NARRATION'):
                rowop=rowop+f'<NARRATION>{row_value}</NARRATION>\n'
                continue

            if att[i].startswith('Buyer_Name'):
                b_name = row_value
                rowop=rowop+f'<BASICBUYERNAME>{row_value}</BASICBUYERNAME>\n<CONSIGNEEMAILINGNAME>{b_name}</CONSIGNEEMAILINGNAME>\n<PARTYNAME>{row_value}</PARTYNAME>\n<PARTYMAILINGNAME>{row_value}</PARTYMAILINGNAME>\n'
                continue

            if att[i].startswith('Pincode'):
                pin_code = row_value
                if row_value == 'emp':
                    continue
                rowop=rowop+f'<PARTYPINCODE>{row_value}</PARTYPINCODE>\n<CONSIGNEEPINCODE>{row_value}</CONSIGNEEPINCODE>\n'
                continue

            if att[i].startswith('State_Name'):
                s_name = row_value
                if row_value == 'emp':
                    continue
                rowop=rowop+f'<STATENAME>{row_value}</STATENAME>\n<BILLTOPLACE>{row_value}</BILLTOPLACE>\n<CONSIGNEESTATENAME>{row_value}</CONSIGNEESTATENAME>\n'
                continue

            if att[i].startswith('Address_1'):
                if row_value == 'emp':
                    line1 =''
                    continue
                else:
                    line1 = row_value
                    continue
            if att[i].startswith('Address_2'):
                if row_value == 'emp':
                    line2 =''
                    continue
                else:
                    line2 = row_value
                    continue
            if att[i].startswith('Address_3'):
                if row_value == 'emp':
                    line3 =''
                    continue
                else:
                    line3 = row_value
                    continue
            if att[i].startswith('Address_4'):
                if row_value == 'emp':
                    line4 =''
                else:
                    line4 = row_value
                rowop=rowop+f'<ADDRESS.LIST TYPE="String">\n<ADDRESS>{line1}</ADDRESS>\n<ADDRESS>{line2}</ADDRESS>\n<ADDRESS>{line3}</ADDRESS>\n<ADDRESS>{line4}</ADDRESS>\n</ADDRESS.LIST>\n<BASICBUYERADDRESS.LIST TYPE="String">\n<BASICBUYERADDRESS>{line1}</BASICBUYERADDRESS>\n<BASICBUYERADDRESS>{line2}</BASICBUYERADDRESS>\n<BASICBUYERADDRESS>{line3}</BASICBUYERADDRESS>\n<BASICBUYERADDRESS>{line4}</BASICBUYERADDRESS>\n</BASICBUYERADDRESS.LIST>\n'
                continue

            if att[i].startswith('POS'):
                pos = row_value
                rowop=rowop+f'<PLACEOFSUPPLY>{row_value}</PLACEOFSUPPLY>\n<SHIPTOPLACE>{row_value}</SHIPTOPLACE>\n'
                continue
            if att[i].startswith('Country'):
                pos = row_value
                rowop=rowop+f'<COUNTRYOFRESIDENCE>{row_value}</COUNTRYOFRESIDENCE>'
                continue
            if att[i].startswith('Registration_Type'):
                r_type = row_value
                continue
            if att[i].startswith('Company_GSTIN'):
                if row_value == 'emp':
                    continue
                rowop=rowop+f'<PARTYGSTIN>{row_value}</PARTYGSTIN>\n<CONSIGNEEGSTIN>{row_value}</CONSIGNEEGSTIN>\n'
                gstin = row_value
                continue

            if att[i].startswith('DebitLedger'):
                if row_value == 'emp':
                    continue
                rowop=rowop+f'<PARTYLEDGERNAME>{row_value}</PARTYLEDGERNAME>\n<LEDGERENTRIES.LIST>\n<LEDGERNAME>{row_value}</LEDGERNAME>\n'
                continue
            if att[i].startswith('AmountDebit'):
                if row_value == 'emp':
                    continue
                rowop=rowop+f'<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>\n<ISPARTYLEDGER>Yes</ISPARTYLEDGER>\n<AMOUNT>{row_value}</AMOUNT>\n<BILLALLOCATIONS.LIST>\n<NAME>{inv_no}</NAME>\n<BILLTYPE>{inv_no}</BILLTYPE>\n<AMOUNT>{row_value}</AMOUNT>\n</BILLALLOCATIONS.LIST>\n</LEDGERENTRIES.LIST>'
                continue
            # if att[i].startswith('CreditLedger'):
            #     if row_value == 'emp':
            #         continue
            #     rowop=rowop+f'<ALLLEDGERENTRIES.LIST>\n<LEDGERNAME>{row_value}</LEDGERNAME>\n'
            #     continue
            # if att[i].startswith('AmountCredit'):
            #     if row_value == 'emp' and i == len(att)-1:
            #         rowop=rowop+f'</VOUCHER>\n</TALLYMESSAGE>\n'
            #         continue
            #     elif row_value == 'emp':
            #         continue
            #     elif i == len(att)-1:
            #         rowop=rowop+f'<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>\n<AMOUNT>{row_value}</AMOUNT>\n</ALLLEDGERENTRIES.LIST>\n</VOUCHER>\n</TALLYMESSAGE>\n'
            #         continue
            #     else:
            #         rowop=rowop+f'<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>\n<AMOUNT>{row_value}</AMOUNT>\n</ALLLEDGERENTRIES.LIST>\n'

            else:
                #print('where Am I',att[i])
                l_name=att[i]
                if '&' in att[i]:
                    l_name = att[i].replace('&', '&amp;', att[i].count('&'))
                if '<' in att[i]:
                    l_name = att[i].replace('<', '&lt;', att[i].count('<'))
                if '>' in att[i]:
                    l_name = att[i].replace('>', '&gt;', att[i].count('>'))
                if "'" in att[i]:
                    l_name = att[i].replace("'", '&apos;', att[i].count("'"))
                if '"' in att[i]:
                    l_name = att[i].replace('"', '&quot;', att[i].count('"'))
                if i == len(att)-1 and row_value == 'emp':
                    rowop=rowop+f'</VOUCHER>\n</TALLYMESSAGE>\n'
                if row_value == 'emp':
                    continue
                if not l_name.startswith(("CGST", "IGST", "SGST")):
                    if att[i].startswith('Cost_Centre'):
                        continue
                    else:
                        # print("--------",l_name, cost_category ,'centerrrr', df[att[i+1]][j] , att[i][j])
                        rowop = rowop + f"""
                        <LEDGERENTRIES.LIST>
                            <LEDGERNAME>{l_name}</LEDGERNAME>
                            <GSTCLASS/>
                            <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                            <ISPARTYLEDGER>No</ISPARTYLEDGER>
                            <AMOUNT>{row_value}</AMOUNT>
                            <CATEGORYALLOCATIONS.LIST>
                                <CATEGORY>{cost_category}</CATEGORY>
                                <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                                <COSTCENTREALLOCATIONS.LIST>
                                    <NAME>{df[att[i+1]][j]}</NAME>
                                    <AMOUNT>{row_value}</AMOUNT>
                                </COSTCENTREALLOCATIONS.LIST>
                            </CATEGORYALLOCATIONS.LIST>
                        </LEDGERENTRIES.LIST>
                        """
                else:
                    if i != len(att)-1:
                        #print('Whywyehy', l_name)
                        #print('where Am I Should be the last time',att[i])
                        rowop = rowop + f"""
                        <LEDGERENTRIES.LIST>
                            <LEDGERNAME>{l_name}</LEDGERNAME>
                            <GSTCLASS/>
                            <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                            <ISPARTYLEDGER>No</ISPARTYLEDGER>
                            <AMOUNT>{row_value}</AMOUNT>
                        </LEDGERENTRIES.LIST>
                        """
                    else:
                        rowop = rowop + f"""
                        <LEDGERENTRIES.LIST>
                            <LEDGERNAME>{l_name}</LEDGERNAME>
                            <GSTCLASS/>
                            <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                            <ISPARTYLEDGER>No</ISPARTYLEDGER>
                            <AMOUNT>{row_value}</AMOUNT>
                        </LEDGERENTRIES.LIST>\n</VOUCHER>\n</TALLYMESSAGE>\n
                        """

        srop = srop + f'<TALLYMESSAGE xmlns:UDF="TallyUDF">\n<VOUCHER VCHTYPE="{v_type}" ACTION="Create" OBJVIEW="Accounting Voucher View">\n' + rowop
    entireop=header+srop+footer
    with open(outputfile,'w+') as f:
        f.write(entireop)
CSVtoXML('INV.csv')

import xml.etree.ElementTree as ET
import pandas as pd

def create_jv_xml(df, out_path="jv.xml"):
    
    envelope = ET.Element("ENVELOPE")
    header = ET.SubElement(envelope, "HEADER")
    ET.SubElement(header, "TALLYREQUEST").text = "Import Data"

    body = ET.SubElement(envelope, "BODY")
    importdata = ET.SubElement(body, "IMPORTDATA")
    requestdesc = ET.SubElement(importdata, "REQUESTDESC")
    ET.SubElement(requestdesc, "REPORTNAME").text = "All Masters"
    requestdata = ET.SubElement(importdata, "REQUESTDATA")

    for _, row in df.iterrows():

        date_val = str(row["DATE"])
        inv_no = str(row["VOUCHERNUMBER"])
        orig_narr = str(row.get("NARRATION", ""))

        # Detect COD or PPD
        mode = "PPD" if "PPD" in orig_narr.upper() else "COD"

        # Correct JV narration
        narration_text = f"Being Transfer entry passed against INV No.: {inv_no} for Nexus storefront - {mode}"

        # Ledger logic
        base_ledger = str(row["DebitLedger"])

        if mode == "PPD":
            suffix = "_Nexus_PPD_V"
        else:
            suffix = "_Nexus_COD_V"

        if base_ledger.endswith("_C"):
            debit_ledger = base_ledger[:-2] + suffix
        else:
            debit_ledger = base_ledger + suffix

        amt = float(row["AmountDebitLedger"])
        debit_amt = -abs(amt)
        credit_amt = abs(amt)

        # === VALID TALLY STRUCTURE ===
        tallymsg = ET.SubElement(requestdata, "TALLYMESSAGE", {"xmlns:UDF": "TallyUDF"})
        voucher = ET.SubElement(tallymsg, "VOUCHER",
                                {"VCHTYPE": "S-JV",
                                 "ACTION": "Create",
                                 "OBJVIEW": "Accounting Voucher View"})

        ET.SubElement(voucher, "DATE").text = date_val
        ET.SubElement(voucher, "PARTYLEDGERNAME").text = base_ledger  # same as your working file
        ET.SubElement(voucher, "VOUCHERTYPENAME").text = "S-JV"
        ET.SubElement(voucher, "REFERENCE").text = "On Account"
        ET.SubElement(voucher, "Narration").text = narration_text

        # DEBIT LEG
        leg1 = ET.SubElement(voucher, "ALLLEDGERENTRIES.LIST")
        ET.SubElement(leg1, "LEDGERNAME").text = debit_ledger
        ET.SubElement(leg1, "ISDEEMEDPOSITIVE").text = "Yes"
        ET.SubElement(leg1, "AMOUNT").text = str(debit_amt)

        # CREDIT LEG
        leg2 = ET.SubElement(voucher, "ALLLEDGERENTRIES.LIST")
        ET.SubElement(leg2, "LEDGERNAME").text = base_ledger
        ET.SubElement(leg2, "ISDEEMEDPOSITIVE").text = "No"
        ET.SubElement(leg2, "AMOUNT").text = str(credit_amt)

    # Save XML
    tree = ET.ElementTree(envelope)
    tree.write(out_path, encoding="utf-8", xml_declaration=True)
    print("✅ JV XML generated:", out_path)

# ---- RUN BOTH STEPS ----
if __name__ == "__main__":
    # 1) Create sale XML from CSV (already working)
    CSVtoXML('INV.csv')

    # 2) Create JV XML from same CSV
    df = pd.read_csv("INV.csv")
    create_jv_xml(df, "jv.xml")
    print("JV XML Created Successfully")
