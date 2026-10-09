"""Generate synthetic, readable Arabic/English fixtures with real PDF text and image pixels."""
from pathlib import Path
import html
import pymupdf
from PIL import Image, ImageFilter, ImageEnhance

ROOT = Path(__file__).resolve().parent
FONT = Path('C:/Windows/Fonts/arial.ttf')
if not FONT.exists(): FONT = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
CSS = '''body {font-family: sans-serif; font-size:12pt; color:#163344;} h1 {font-size:25pt; color:#087b72;}
.small {font-size:9pt; color:#70818c;} table {width:100%; border-collapse:collapse; margin-top:24px; table-layout:fixed;}
th {background:#e3f0ed; text-align:left; font-size:10pt;} td,th {padding:9px 5px; border-bottom:1px solid #d6e0e3;}
td {font-size:10pt;} .meta {line-height:1.7;} .totals {margin-top:25px; line-height:1.8;}'''


def build(name, kind, language='en', multipage=False):
    arabic = language == 'ar'
    bilingual = language == 'mixed'
    titles = {'purchase_order': ('PURCHASE ORDER', 'أمر شراء'), 'supplier_invoice': ('SUPPLIER INVOICE', 'فاتورة المورد'), 'goods_receipt': ('DELIVERY NOTE', 'إشعار التسليم')}
    refs = {'purchase_order': 'PO-2026-001', 'supplier_invoice': 'INV-2026-001', 'goods_receipt': 'DN-2026-001'}
    number_labels = {'purchase_order': ('PO number', 'رقم أمر الشراء'), 'supplier_invoice': ('Invoice number', 'رقم الفاتورة'), 'goods_receipt': ('Delivery note number', 'رقم إشعار التسليم')}
    date_labels = {'purchase_order': ('Order date', 'تاريخ الطلب'), 'supplier_invoice': ('Invoice date', 'تاريخ الفاتورة'), 'goods_receipt': ('Delivery date', 'تاريخ التسليم')}
    labels = [('Supplier', 'المورد', 'شركة النور للكابلات' if arabic or bilingual else 'Noor Cable Supplies'),
              ('Buyer', 'المشتري', 'شركة المدار للمقاولات' if arabic else 'Madar Projects'),
              (*number_labels[kind], refs[kind]), (*date_labels[kind], '2026-10-09'),
              ('Currency', 'العملة', 'SAR'), ('Supplier VAT', 'الرقم الضريبي للمورد', '300000000000003')]
    if kind != 'purchase_order': labels.append(('PO reference', 'مرجع أمر الشراء', 'PO-2026-001'))
    if kind == 'supplier_invoice': labels.append(('Due date', 'تاريخ الاستحقاق', '2026-11-08'))
    if kind == 'purchase_order': labels.append(('Expected delivery date', 'تاريخ التسليم المتوقع', '2026-10-15'))
    columns = ['رمز', 'الوصف', 'الكمية', 'الوحدة'] if arabic else ['SKU', 'Description', 'Quantity', 'Unit']
    if kind != 'goods_receipt': columns += ['السعر', 'المبلغ'] if arabic else ['Unit price', 'Amount']
    quantity = '90' if kind == 'goods_receipt' else '100'
    price = '50.00' if kind == 'purchase_order' else '55.00'
    total = '5000.00' if kind == 'purchase_order' else '5500.00'
    digits = str.maketrans('0123456789.', '٠١٢٣٤٥٦٧٨٩٫')
    doc = pymupdf.open()
    for page_index in range(2 if multipage else 1):
        title = titles[kind][1 if arabic else 0]
        if bilingual: title += ' / فاتورة المورد'
        meta = ''.join(f'<div dir="auto">{html.escape(ar if arabic else en)}: <span dir="{ "rtl" if any("\u0600" <= c <= "\u06ff" for c in value) else "ltr" }">{html.escape(value)}</span></div>' for en, ar, value in labels)
        description = 'لفات كابلات كهربائية' if arabic or bilingual else 'Electrical Cable Rolls'
        row = ['CBL-100', description, quantity.translate(digits) if arabic else quantity, 'لفة' if arabic else 'roll']
        if kind != 'goods_receipt': row += [price, total]
        table = '<table><colgroup><col style="width:14%"><col style="width:32%"><col style="width:13%"><col style="width:10%"><col style="width:15%"><col style="width:16%"></colgroup><tr>' + ''.join(f'<th>{c}</th>' for c in columns) + '</tr><tr>' + ''.join(f'<td dir="{ "rtl" if i in (1,3) and (arabic or bilingual) else "ltr" }">{v}</td>' for i,v in enumerate(row)) + '</tr></table>'
        totals = ''
        if kind != 'goods_receipt' and (not multipage or page_index == 1):
            from decimal import Decimal
            amount = str(Decimal(total) * (2 if multipage else 1))
            for en, ar, value in [('Subtotal', 'المجموع الفرعي', amount), ('Discount', 'الخصم', '0.00'), ('VAT', 'الضريبة', '0.00'), ('Grand total', 'المجموع الكلي', amount)]:
                totals += f'<div dir="auto">{ar if arabic else en}: {value.translate(digits) if arabic else value}</div>'
        content = f'<p class="small">MATCHLEDGER / SYNTHETIC SAMPLE / {page_index+1}</p><h1 dir="auto">{title}</h1><div class="meta">{meta}</div>{table}<div class="totals">{totals}</div><p class="small">Fictional companies and financial data. All amounts exclude VAT.</p>'
        page = doc.new_page(width=700, height=920)
        font_css = f'@font-face {{font-family: fixture; src: url({FONT.name});}} body {{font-family: fixture;}}' if FONT.exists() else ''
        spare, scale = page.insert_htmlbox(pymupdf.Rect(40, 35, 660, 880), content, css=CSS + font_css, archive=pymupdf.Archive(str(FONT.parent)) if FONT.exists() else None)
        if scale < 0.95: raise RuntimeError('Fixture content unexpectedly shrank')
    doc.save(ROOT / name)
    doc.close()


if __name__ == '__main__':
    for kind, label in [('purchase_order', 'purchase_order'), ('supplier_invoice', 'invoice'), ('goods_receipt', 'delivery_note')]:
        for language in ('en', 'ar'): build(f'{label}_{language}.pdf', kind, language)
    build('invoice_bilingual.pdf', 'supplier_invoice', 'mixed')
    build('invoice_multipage.pdf', 'supplier_invoice', multipage=True)
    with pymupdf.open(ROOT / 'invoice_en.pdf') as doc:
        pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
        image.save(ROOT / 'invoice_scanned.png')
        image.save(ROOT / 'invoice_scanned.jpg', quality=90)
        low = image.resize((420, 552)).filter(ImageFilter.GaussianBlur(1.1))
        low = ImageEnhance.Contrast(low).enhance(0.35)
        low.save(ROOT / 'invoice_low_quality.jpg', quality=40)
        with pymupdf.open() as scanned:
            page = scanned.new_page(width=700, height=920)
            page.insert_image(page.rect, filename=str(ROOT / 'invoice_scanned.png'))
            (ROOT / 'invoice_scanned.pdf').write_bytes(scanned.tobytes())
    print('Created eight native PDFs, one scanned PDF and three images.')
