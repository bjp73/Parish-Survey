#!/usr/bin/env python3
"""
Full survey digitisation workflow scaffold for the Holy Family Parish folded-A3 survey.

What this script does:
1. Extracts PDF pages in small chunks using pdftoppm, so large 600 dpi PDFs are easier to process.
2. Pairs pages sequentially: 1-2, 3-4, 5-6, etc.
3. Creates an Excel workbook with:
   - Digitised responses sheet using the known survey schema
   - Source page pairs sheet with embedded page images for review
   - ERROR review tab scaffold

Important:
This script prepares the workbook and page evidence. The final transcription logic must either be
completed manually in the workbook, or extended with calibrated optical mark recognition coordinates
for the exact printed survey design.

Usage:
  python full_survey_digitisation_workflow.py --pdf doc20260817081216.pdf --output survey_digitisation.xlsx
"""
from __future__ import annotations
import argparse, os, subprocess, glob
from pathlib import Path
from PIL import Image
import xlsxwriter

HEADERS = ['Survey ID','PDF pages','Review status','Error / review notes','Q1 Years attending','Q2 New attendee description','Q3 Parish activities','Q3 Other text','Q4 Giving last week','Q5a Good friend in Parish','Q5b Can chat after Mass','Q5c Parish activity friends','Q6 Invited someone','Q7 Asked about YOUR wellbeing','Q8 Asked about THEIR wellbeing','Q9 Sacraments received','Q10a Faith shapes life','Q10b Observe Catholic practices','Q10c Accept Catholic teaching','Q11 Last attended Sunday Mass','Q12 Private devotional frequency','Q13 Volunteer hours last week','Q14 Audio-visual materials','Q14 Other text','Q15 Read Catholic book','Q16 Spoken to non-Catholic','Q17 Faith most important','Q18 Age','Q19 Gender','Q20 Household composition','Q20 Other text','Q21 Ethnicity','Q21 Other text','Q22 Highest qualification','Q23 Household income','Q24 Work type','Q24 Other text','Q25 Suburb','Q26 Mass attended','Q27 Feedback/comments']

def extract_pages(pdf, page_dir, dpi=100, chunk=10):
    page_dir = Path(page_dir)
    page_dir.mkdir(parents=True, exist_ok=True)
    # Use pdfinfo if available to get page count. If not, user can provide extracted images separately.
    page_count = None
    try:
        p = subprocess.run(['pdfinfo', pdf], capture_output=True, text=True, check=True)
        for line in p.stdout.splitlines():
            if line.startswith('Pages:'):
                page_count = int(line.split(':',1)[1].strip())
                break
    except Exception:
        pass
    if page_count is None:
        raise RuntimeError('Could not determine page count. Install poppler-utils/pdfinfo or extract pages separately.')
    for start in range(1, page_count + 1, chunk):
        end = min(start + chunk - 1, page_count)
        subprocess.run(['pdftoppm','-png','-r',str(dpi),'-f',str(start),'-l',str(end),pdf,str(page_dir/'page')], check=True)
    return sorted(glob.glob(str(page_dir/'page-*.png')))

def build_workbook(page_files, output, source_pdf):
    pairs=[]
    page_files=sorted(page_files)
    for i in range(0, len(page_files)-len(page_files)%2, 2):
        pairs.append((i//2+1,page_files[i],page_files[i+1]))
    wb=xlsxwriter.Workbook(output)
    header=wb.add_format({'bold':True,'bg_color':'#1F4E78','font_color':'white','text_wrap':True,'valign':'top'})
    wrap=wb.add_format({'text_wrap':True,'valign':'top'})
    review=wb.add_format({'bg_color':'#FCE4D6','text_wrap':True,'valign':'top'})
    ws=wb.add_worksheet('Digitised responses')
    for c,h in enumerate(HEADERS): ws.write(0,c,h,header)
    for r,(sid,p1,p2) in enumerate(pairs,1):
        pdf_pages=f"{Path(p1).stem.split('-')[-1]}-{Path(p2).stem.split('-')[-1]}"
        ws.write(r,0,sid,wrap); ws.write(r,1,pdf_pages,wrap)
        ws.write(r,2,'Ready for transcription',review)
        ws.write(r,3,'Review paired page images and enter answers.',review)
    ws.freeze_panes(1,4); ws.autofilter(0,0,len(pairs),len(HEADERS)-1)
    for c in range(len(HEADERS)): ws.set_column(c,c,18)
    ws=wb.add_worksheet('Source page pairs')
    for c,h in enumerate(['Survey ID','PDF pages','First scan page image','Second scan page image']): ws.write(0,c,h,header)
    ws.set_column(0,1,12); ws.set_column(2,3,55)
    for r,(sid,p1,p2) in enumerate(pairs,1):
        ws.set_row(r,210); ws.write(r,0,sid,wrap); ws.write(r,1,f"{Path(p1).stem.split('-')[-1]}-{Path(p2).stem.split('-')[-1]}",wrap)
        for col,p in [(2,p1),(3,p2)]:
            im=Image.open(p); scale=300/im.width; ws.insert_image(r,col,p,{'x_scale':scale,'y_scale':scale})
    ws=wb.add_worksheet('ERROR review')
    for c,h in enumerate(['Survey ID','PDF pages','Question','Current value','Reason for review','Source page','Cropped image']): ws.write(0,c,h,header)
    ws.write(1,0,'Populate after transcription',review)
    ws=wb.add_worksheet('Method')
    ws.write(0,0,'Source PDF',header); ws.write(0,1,source_pdf,wrap)
    ws.write(1,0,'Rows prepared',header); ws.write(1,1,len(pairs),wrap)
    wb.close()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--pdf', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--dpi', type=int, default=100)
    ap.add_argument('--chunk', type=int, default=10)
    ap.add_argument('--page-dir', default='extracted_pages')
    args=ap.parse_args()
    pages=extract_pages(args.pdf,args.page_dir,args.dpi,args.chunk)
    build_workbook(pages,args.output,args.pdf)
    print(f'Wrote {args.output} with {len(pages)//2} survey rows.')
if __name__=='__main__': main()
