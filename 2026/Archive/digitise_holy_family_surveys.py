#!/usr/bin/env python3
"""
Digitise Holy Family Parish paper survey responses into Excel.

This script is designed for the specific 4-page Holy Family Parish survey form that
was printed as folded A3 and scanned as adjacent page pairs. It creates a structured
Excel workbook with one row per completed survey.

Important limitation:
- The structured ANSWER_ROWS section below is where reviewed answers are stored.
- The optional OCR extraction helps with review, but OCR alone will not reliably
  identify all ticks/circles/handwriting. For best accuracy, review the page images
  and update ANSWER_ROWS before writing the final workbook.

Typical use:
  python digitise_holy_family_surveys.py --output survey_responses.xlsx

Optional OCR support, if pdftoppm and tesseract are installed:
  python digitise_holy_family_surveys.py --pdf "3 surveys 600 dpi full color.pdf" --output survey_responses.xlsx
"""

from __future__ import annotations
import argparse
import csv
import os
import subprocess
from pathlib import Path
from typing import List, Any, Optional

import xlsxwriter

HEADERS = [
    'Survey ID','PDF pages','Review status','Error / review notes',
    'Q1 Years attending','Q2 New attendee description','Q3 Parish activities','Q3 Other text','Q4 Giving last week',
    'Q5a Good friend in Parish','Q5b Can chat after Mass','Q5c Parish activity friends',
    'Q6 Invited someone','Q7 Asked about YOUR wellbeing','Q8 Asked about THEIR wellbeing',
    'Q9 Sacraments received','Q10a Faith shapes life','Q10b Observe Catholic practices','Q10c Accept Catholic teaching',
    'Q11 Last attended Sunday Mass','Q12 Private devotional frequency','Q13 Volunteer hours last week',
    'Q14 Audio-visual materials','Q14 Other text','Q15 Read Catholic book','Q16 Spoken to non-Catholic','Q17 Faith most important',
    'Q18 Age','Q19 Gender','Q20 Household composition','Q20 Other text','Q21 Ethnicity','Q21 Other text',
    'Q22 Highest qualification','Q23 Household income','Q24 Work type','Q24 Other text','Q25 Suburb','Q26 Mass attended','Q27 Feedback/comments'
]

# Reviewed rows for the 600 dpi full-colour test batch. Update or extend this list for future batches.
ANSWER_ROWS: List[List[Any]] = [
    [1,'1-2','Review recommended','600 dpi colour scan. Most answers legible; Q10/Q26 should be spot-checked.',
     'Less than 2 years',"I've come from another Catholic parish in Christchurch or elsewhere in New Zealand",
     'Prayer or bible study group','', 'None', '9','1','1','No','No','No',
     'Baptism; Confirmation', '6','7','7','A few months ago','Less than once a week','Up to two hours',
     'None','', 'No','No','9','16 - 20 years','Female','Living alone','', 'NZ European','',
     'Tertiary Qualification',"Don't know/Not sure",'Student','', 'Riccarton','ERROR: Sunday 9am and Sunday 7pm both appear marked',''],

    [2,'3-4','Review recommended','600 dpi colour scan. Other text in Q3 is partly handwritten; Q5/Q10 scale values should be spot-checked.',
     'Between 11 - 20 years','', 'Other','children attend the group for First Holy Communion', '$11-$20',
     '3','2','2','No','No','No','Baptism; First Communion; Confirmation; Anointing of the Sick',
     '6','6','7','Two weeks ago','Once a week','None','Recorded Lectures','', 'Yes','Yes','9',
     '41-50 years','Female','Couple, no children at home','', 'Indian','', 'High school graduate/NCEA level 3',
     '$80,001 - $100,000','Full time paid work','', 'Hornby','Sunday 7pm',''],

    [3,'5-6','Review recommended','600 dpi colour scan. Q13 and Q26 should be spot-checked; most remaining responses are legible.',
     'Less than 2 years',"I've come from another Catholic parish in Christchurch or elsewhere in New Zealand",
     'None of the above','', 'None', '7','9','9','No','No','No','Confirmation',
     '7','9','9','Last Sunday','Four to six times a week','Up to two hours','None','', 'No','No','7',
     '16 - 20 years','Male','Family, mainly adult children at home','', 'NZ European','', 'Tertiary Qualification',
     '$80,001 - $100,000','Student','', 'Ilam','ERROR: Sunday 9am and Sunday 7pm both appear marked','']
]

QUESTION_TYPES = {
    'Survey ID':'id','PDF pages':'metadata','Review status':'metadata','Error / review notes':'metadata',
    'Q1 Years attending':'single','Q2 New attendee description':'single','Q3 Parish activities':'multi','Q3 Other text':'text',
    'Q4 Giving last week':'single','Q5a Good friend in Parish':'scale','Q5b Can chat after Mass':'scale','Q5c Parish activity friends':'scale',
    'Q6 Invited someone':'single','Q7 Asked about YOUR wellbeing':'single','Q8 Asked about THEIR wellbeing':'single',
    'Q9 Sacraments received':'multi','Q10a Faith shapes life':'scale','Q10b Observe Catholic practices':'scale','Q10c Accept Catholic teaching':'scale',
    'Q11 Last attended Sunday Mass':'single','Q12 Private devotional frequency':'single','Q13 Volunteer hours last week':'single',
    'Q14 Audio-visual materials':'multi','Q14 Other text':'text','Q15 Read Catholic book':'single','Q16 Spoken to non-Catholic':'single','Q17 Faith most important':'scale',
    'Q18 Age':'single','Q19 Gender':'single','Q20 Household composition':'single','Q20 Other text':'text','Q21 Ethnicity':'multi','Q21 Other text':'text',
    'Q22 Highest qualification':'single','Q23 Household income':'single','Q24 Work type':'single','Q24 Other text':'text','Q25 Suburb':'text','Q26 Mass attended':'single','Q27 Feedback/comments':'text'
}


def maybe_extract_ocr(pdf_path: Optional[str], workdir: Path) -> List[List[str]]:
    """Return rows [page_number, ocr_text_file, ocr_text] if OCR tools are available."""
    if not pdf_path:
        return []
    pdf = Path(pdf_path)
    if not pdf.exists():
        return [["ERROR", "", f"PDF not found: {pdf}"]]
    pages_dir = workdir / 'ocr_pages'
    pages_dir.mkdir(parents=True, exist_ok=True)
    prefix = pages_dir / 'page'
    try:
        subprocess.run(['pdftoppm', '-png', '-r', '200', str(pdf), str(prefix)], check=True, capture_output=True, text=True)
    except Exception as exc:
        return [["ERROR", "", f"pdftoppm failed or is not installed: {exc}"]]
    ocr_rows = []
    for image_path in sorted(pages_dir.glob('page-*.png')):
        txt_base = image_path.with_suffix('')
        try:
            subprocess.run(['tesseract', str(image_path), str(txt_base), '--psm', '6'], check=True, capture_output=True, text=True)
            txt_path = txt_base.with_suffix('.txt')
            text = txt_path.read_text(errors='replace') if txt_path.exists() else ''
        except Exception as exc:
            txt_path = ''
            text = f"tesseract failed or is not installed: {exc}"
        page_number = image_path.stem.split('-')[-1]
        ocr_rows.append([page_number, str(txt_path), text[:32000]])
    return ocr_rows


def write_workbook(rows: List[List[Any]], output_path: str, source_pdf: Optional[str] = None, ocr_rows: Optional[List[List[str]]] = None) -> None:
    workbook = xlsxwriter.Workbook(output_path)
    header_fmt = workbook.add_format({'bold': True, 'bg_color': '#1F4E78', 'font_color': 'white', 'text_wrap': True, 'valign': 'top'})
    error_fmt = workbook.add_format({'bg_color': '#F4CCCC', 'text_wrap': True, 'valign': 'top'})
    review_fmt = workbook.add_format({'bg_color': '#FCE4D6', 'text_wrap': True, 'valign': 'top'})
    wrap_fmt = workbook.add_format({'text_wrap': True, 'valign': 'top'})

    ws = workbook.add_worksheet('Digitised responses')
    for c, h in enumerate(HEADERS):
        ws.write(0, c, h, header_fmt)
    for r, row in enumerate(rows, start=1):
        for c, value in enumerate(row):
            fmt = wrap_fmt
            if isinstance(value, str) and 'ERROR' in value:
                fmt = error_fmt
            elif isinstance(value, str) and ('UNCLEAR' in value or 'Review recommended' in value):
                fmt = review_fmt
            ws.write(r, c, value, fmt)
    ws.freeze_panes(1, 4)
    ws.autofilter(0, 0, len(rows), len(HEADERS)-1)
    for c in range(len(HEADERS)):
        width = 18
        if c in [3, 39]: width = 45
        if c in [6, 15, 22, 31]: width = 35
        if c in [0, 1, 2]: width = 16
        ws.set_column(c, c, width)

    notes = workbook.add_worksheet('Method and review notes')
    note_rows = [
        ['Item','Note'],
        ['Source PDF', source_pdf or 'Not specified'],
        ['Page pairing','Each survey uses adjacent page pairs from the folded A3 scan. Use question numbering to interpret page order.'],
        ['Record count', f'{len(rows)} survey records in this workbook.'],
        ['Scan quality note','600 dpi full-colour scans materially improve legibility of blue ink ticks and handwritten comments compared with lower-resolution grayscale scans.'],
        ['ERROR meaning','Illegal response detected or suspected, usually multiple selections on a single-choice question.'],
        ['UNCLEAR meaning','Answer or handwriting could not be deciphered with sufficient confidence.'],
        ['Workflow','Review page images and OCR text, update ANSWER_ROWS in this script, then rerun the script to create the workbook.']
    ]
    for r, row in enumerate(note_rows):
        for c, value in enumerate(row):
            notes.write(r, c, value, header_fmt if r == 0 else wrap_fmt)
    notes.set_column(0, 0, 24)
    notes.set_column(1, 1, 110)

    schema = workbook.add_worksheet('Question schema')
    schema.write(0, 0, 'Column', header_fmt)
    schema.write(0, 1, 'Question/type', header_fmt)
    for r, h in enumerate(HEADERS, start=1):
        schema.write(r, 0, h, wrap_fmt)
        schema.write(r, 1, QUESTION_TYPES.get(h, ''), wrap_fmt)
    schema.set_column(0, 0, 45)
    schema.set_column(1, 1, 18)

    if ocr_rows:
        ocr = workbook.add_worksheet('OCR text by page')
        for c, h in enumerate(['Page', 'OCR text file', 'OCR text preview']):
            ocr.write(0, c, h, header_fmt)
        for r, row in enumerate(ocr_rows, start=1):
            for c, value in enumerate(row):
                ocr.write(r, c, value, wrap_fmt)
        ocr.set_column(0, 0, 10)
        ocr.set_column(1, 1, 45)
        ocr.set_column(2, 2, 120)

    workbook.close()


def main() -> None:
    parser = argparse.ArgumentParser(description='Create Holy Family Parish survey response workbook.')
    parser.add_argument('--pdf', default=None, help='Optional source PDF to OCR for review support.')
    parser.add_argument('--output', default='Holy_Family_Parish_Survey_600dpi_Responses.xlsx', help='Output .xlsx file path.')
    args = parser.parse_args()

    workdir = Path(args.output).resolve().parent
    ocr_rows = maybe_extract_ocr(args.pdf, workdir) if args.pdf else []
    write_workbook(ANSWER_ROWS, args.output, source_pdf=args.pdf, ocr_rows=ocr_rows)
    print(f'Wrote {args.output}')

if __name__ == '__main__':
    main()
