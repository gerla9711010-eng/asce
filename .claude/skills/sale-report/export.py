# -*- coding: utf-8 -*-
"""產完 PPT 之後：逐頁出 PNG（給 Claude 檢查版面）＋合成 PDF＋PPT/PDF 各複製一份到桌面根目錄。

用法:  python export.py <報告書.pptx> [PNG 檢查資料夾]

- 本機 PowerPoint 是 2007：SaveAs PDF 會 RPC_E_SERVERFAULT，所以 PDF 是用 2400×1350 PNG
  經 reportlab 合成（每頁是圖，字不能選取）。PIL 存 PDF 不行（這台的 Pillow 沒有 JPEG 外掛）。
- 複製到桌面失敗＝使用者正開著那份檔案，請他關掉再跑一次，不要改檔名繞過。
"""
import glob
import os
import re
import shutil
import sys
import tempfile

DESKTOP = r'C:\Users\user\OneDrive\桌面'


def export_png(pptx, out_dir, w, h):
    import win32com.client
    os.makedirs(out_dir, exist_ok=True)
    for f in glob.glob(os.path.join(out_dir, '*.PNG')):
        os.remove(f)
    app = win32com.client.Dispatch('PowerPoint.Application')
    pres = app.Presentations.Open(os.path.abspath(pptx), True, False, False)
    try:
        pres.Export(os.path.abspath(out_dir), 'PNG', w, h)
    finally:
        pres.Close()
        if app.Presentations.Count == 0:      # 使用者自己開著別的簡報就不要關掉 PowerPoint
            app.Quit()
    return sorted(glob.glob(os.path.join(out_dir, '*.PNG')),
                  key=lambda f: int(re.findall(r'(\d+)\.PNG$', f)[0]))


def to_pdf(pngs, pdf):
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(pdf, pagesize=(960, 540))
    for f in pngs:
        c.drawImage(f, 0, 0, 960, 540)
        c.showPage()
    c.save()


def main(pptx, check_dir=None):
    base = os.path.splitext(pptx)[0]
    check_dir = check_dir or os.path.join(tempfile.gettempdir(), 'sale-report-png')
    small = export_png(pptx, check_dir, 1400, 788)
    big_dir = check_dir + '_hi'
    big = export_png(pptx, big_dir, 2400, 1350)
    to_pdf(big, base + '.pdf')
    shutil.rmtree(big_dir, ignore_errors=True)
    for ext in ('.pptx', '.pdf'):
        dst = os.path.join(DESKTOP, os.path.basename(base) + ext)
        try:
            shutil.copyfile(base + ext, dst)
        except PermissionError:
            print('!! 桌面那份 %s 正被開著，請使用者關掉後再跑一次' % os.path.basename(dst))
    print('檢查用 PNG（%d 頁）: %s' % (len(small), check_dir))
    print('PDF: %s.pdf' % base)


if __name__ == '__main__':
    main(*sys.argv[1:])
