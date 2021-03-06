import pdfquery
import re
from pdfext import *
import json
import os
from pyquery import PyQuery as d
from fields import *
from urllib.request import Request, urlopen
import io

def check_layout_pao_or(data, pq):
    if re.search("PAO([ \(]*)OR([ \)]*)", data["NameOfEmployer"]) or pq(':contains("Name and Rank")'):
        return True

def get_layout(data, pq):
    if check_layout_pao_or(data, pq):
        return "form_16_pao_or"
    else:
        return "other"

y = 0

def filterNonName(i, el):
    global y
    if re.search("PAN|TAN", d(el).text()) or float(el.get("y1")) <= y:
        if y == 0:
            y = float(el.get("y1"))
        return False
    return True

def get_pdf_from_url(url):
    pdf_file = io.BytesIO(urlopen(Request(url)).read())
    return pdf_file

def extract_from_pdf(pdf_file, pdfname):
    print(pdfname)
    pdf = pdfquery.PDFQuery(pdf_file)
    pdf.load()  # creates xml tree from given pdf using elements identified by pdfminer library in pdf
    # os.makedirs("extracted", exist_ok=True)
    global y
    y=0
    data = {
        "NameOfEmployer": column_or_row(
            pdf.pq,  # PyQuery object on which we can query for elements similar to jQuery syntax
            [
                "Name and address of the Employer",
                "Name and Address of the Employer",
                "Deductor Name",
            ],  # list of possible keywords below or along which we want to find the value
            match_col=filterNonName,
        )
    }
    y = 0
    data = {
        **data,
        "NameOfEmployee": column_or_row(
            pdf.pq,
            ["Name and Rank of the Employee", "Employee", "employee",],
            match_col=filterNonName,
        ),
        "PANOfDeductor": column_or_row(
            pdf.pq, ["PAN of the Deductor"], "[A-Z]{5}[0-9]{4}[A-Z]{1}"
        ),
        "TANOfDeductor": column_or_row(
            pdf.pq, ["TAN of the Deductor", "TAN"], "[A-Z]{4}[0-9]{5}[A-Z]{1}"
        ),
        "PANOfEmployee": column_or_row(
            pdf.pq, ["PAN of the Employee", "Emp. PAN"], "[A-Z]{5}[0-9]{4}[A-Z]{1}"
        ),
        "AssessmentYear": column_or_row(pdf.pq, ["Assessment Year"], "[0-9]{4}-[0-9]*"),
        "TDSOnSalary": column_and_row(
            pdf.pq,
            [
                "Amount of tax deposited",
                "Amount of tax deducted/remitted",
            ],  # possible column names
            ["Total"],  # possible row names
        ),
        **get_row_table_start_end_keys(
            pdf.pq, ["FORM NO.12BA"], ["Declaration by Employer",],
        ),
    }

    try:
        data["TDSOnSalary"] = float(data["TDSOnSalary"])
    except ValueError as e:
        data["TDSOnSalary"] = 0.0

    layout = get_layout(data, pdf.pq)
    if layout == "form_16_pao_or":
        # len(sys.argv) > 2 is for determining from command line argument if given input is of PAO(OR) form or not
        # so that we can test on falsified name too (because falsified name does not have PAO OR in name) 
        pao_ors_part_b = {
            **data,
            **PartB("partb", children=[
                grossSalary(
                    "form_16_pao_or_gross_salary",
                    children=[
                        grossSalary171("17(1)"),
                        grossSalary172("17(2)"),
                        grossSalary173("17(3)"),
                        grossSalaryTotal("Total"),
                    ],
                ),
                PAOORAllwncExemptUs10("form_16_pao_or_total_exemptions_under_section_10"),
                DeductionUS16i("form_16_pao_or_standard_deductions_under_section_16_ia"),
                PAOORBalance("form_16_pao_or_balance"),
                PAOORDeductions("Deductions", children=[
                    InterestUS24("form_16_pao_or_other_deductions_interest_payable_on_loan_under_section_24"),
                    Aggregate("form_16_pao_or_other_deductions_aggregate")
                ]),
                OtherIncome("form_16_pao_or_other_income_reported_by_employee"),
                TaxDeductedPartB("form_16_pao_or_tds_amount")
            ]).extract(pdf.pq)
        }
        x = pao_ors_part_b["partb"].pop("Deductions")
        pao_ors_part_b["partb"] = {**pao_ors_part_b["partb"], **x}
        pao_ors_part_b["form_16_pao_or_employer_name"] = pao_ors_part_b.pop("NameOfEmployer")
        pao_ors_part_b["form_16_pao_or_employer_tan"] = pao_ors_part_b.pop("TANOfDeductor")
        pao_ors_part_b["form_16_pao_or_employee_name"] = " ".join(pao_ors_part_b.pop("NameOfEmployee").split(" ")[2:])
        pao_ors_part_b["form_16_pao_or_employee_pan"] = pao_ors_part_b.pop("PANOfEmployee")
        pao_ors_part_b["form_16_pao_or_assessment_year"] = pao_ors_part_b.pop("AssessmentYear")
        pao_ors_part_b.pop("TDSOnSalary")
        data = pao_ors_part_b
    else:

        gross_salary = grossSalary(
            "GrossSalary",
            children=[
                grossSalary171("17(1)"),
                grossSalary172("17(2)"),
                grossSalary173("17(3)"),
                grossSalaryTotal("Total"),
            ],
        )

        allwnc_exempt_us_10 = AllwncExemptUs10("AllwncExemptUs10")
        deduction_us_16 = DeductionUS16(
            "DeductionUS16",
            children=[
                DeductionUS16i("16(i)"),
                DeductionUS16ii("16(ii)"),
                DeductionUS16iii("16(iii)"),
            ],
        )

        if gross_salary.exist(pdf.pq):
            data["GrossSalary"] = gross_salary.extract(pdf.pq)

        if allwnc_exempt_us_10.exist(pdf.pq):
            data = {**data, **allwnc_exempt_us_10.extract(pdf.pq)}

        if deduction_us_16.exist(pdf.pq):
            data = {**data, **deduction_us_16.extract(pdf.pq)}
        else:
            for child in deduction_us_16.children:
                if child.exist(pdf.pq):
                    if deduction_us_16.key in data:
                        data[deduction_us_16.key] = {
                            **data[deduction_us_16.key],
                            child.key: child.extract(pdf.pq)[child.key],
                        }
                    else:
                        data[deduction_us_16.key] = {
                            child.key: child.extract(pdf.pq)[child.key]
                        }
    return data

def extract_from_pdf_name(pdfname):
    return json.dumps(extract_from_pdf(pdfname, pdfname))

def extract_from_pdf_url(url):
    return json.dumps(extract_from_pdf(get_pdf_from_url(url), url))
