'use client';
import { useEffect, useRef, useState } from 'react';
import { Plus, Trash2, X } from 'lucide-react';
import { api, Auth, RecordRow, Line } from '@/lib/api';
import { Button } from './ui/button';

export default function RecordEditor({ resource, record, suppliers, orders, auth, onClose, onSaved }: {
  resource: string; record: RecordRow | null; suppliers: RecordRow[]; orders: RecordRow[]; auth: Auth; onClose: () => void; onSaved: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const supplier = resource === 'suppliers'; const receipt = resource === 'receipts'; const linked = receipt || resource === 'invoices';
  const [poId, setPoId] = useState(record?.purchase_order_id || '');
  const [supplierId, setSupplierId] = useState(record?.supplier_id || '');
  const [currency, setCurrency] = useState(record?.currency || 'SAR');
  const [lines, setLines] = useState<Line[]>(record?.lines || [{ description: '', quantity: '1', unit_price: '0.00' }]);
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  useEffect(() => { ref.current?.showModal(); }, []);
  const po = orders.find(o => o.id === poId);
  function selectPO(id: string) {
    const order = orders.find(o => o.id === id); setPoId(id); setSupplierId(order?.supplier_id || ''); setCurrency(order?.currency || 'SAR');
    setLines(order?.lines?.map(line => ({ description: line.description, quantity: line.quantity, unit_price: line.unit_price, purchase_order_line_id: line.id })) || []);
  }
  function updateLine(index: number, key: string, value: string) { setLines(lines.map((line, i) => i === index ? { ...line, [key]: value } : line)); }
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('');
    const data: { [key: string]: unknown } = Object.fromEntries(new FormData(event.currentTarget));
    if (supplier) { for (const key of ['email', 'phone', 'address', 'external_identifier', 'tax_id']) data[key] = data[key] || null; }
    else {
      data.supplier_id = supplierId;
      if (!receipt) data.currency = currency;
      if (linked) data.purchase_order_id = poId;
      if (resource === 'invoices') for (const key of ['due_date', 'subtotal', 'discount', 'vat_amount', 'grand_total']) data[key] = data[key] || null;
      data.lines = lines.map(line => ({ description: line.description, sku: line.sku || null, unit_of_measure: line.unit_of_measure || null, quantity: line.quantity, ...(!receipt ? { unit_price: line.unit_price } : {}), ...(linked ? { purchase_order_line_id: line.purchase_order_line_id } : {}) }));
    }
    try { await api(`/${resource}${record ? `/${record.id}` : ''}`, { method: record ? 'PUT' : 'POST', body: JSON.stringify(data) }, auth.csrf_token); onSaved(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  const title = supplier ? 'supplier' : receipt ? 'receipt' : resource === 'invoices' ? 'invoice' : 'purchase order';
  return <dialog ref={ref} onCancel={onClose} aria-labelledby="editor-title"><form onSubmit={submit}>
    <div className="flex items-center justify-between p-6 border-b border-slate-100"><div><p className="eyebrow text-teal-700 mb-2">Procurement records</p><h2 id="editor-title" className="text-xl font-semibold">{record ? 'Edit' : 'New'} {title}</h2></div><Button type="button" variant="ghost" onClick={onClose} aria-label="Close editor"><X size={18} /></Button></div>
    <div className="p-6 space-y-5">
      {supplier ? <div className="grid sm:grid-cols-2 gap-5"><label>Supplier name<input name="name" required maxLength={160} defaultValue={record?.name} /></label><label>Email<input name="email" type="email" defaultValue={record?.email} /></label><label>Phone<input name="phone" maxLength={40} defaultValue={record?.phone} /></label><label>External identifier<input name="external_identifier" maxLength={100} defaultValue={record?.external_identifier} /></label><label>Tax ID<input name="tax_id" maxLength={100} defaultValue={record?.tax_id} /></label><label>Address<input name="address" maxLength={1000} defaultValue={record?.address} /></label></div> : <>
        <div className="grid sm:grid-cols-2 gap-5">
          <label>{resource === 'invoices' ? 'Invoice number' : 'Reference number'}<input name="number" required maxLength={80} defaultValue={record?.number} placeholder={receipt ? 'GR-2026-001' : resource === 'invoices' ? 'INV-2026-001' : 'PO-2026-001'} /></label>
          <label>{resource === 'invoices' ? 'Invoice date' : 'Date'}<input name="date" type="date" required defaultValue={record?.date || new Date().toLocaleDateString('en-CA')} /></label>
          {resource === 'invoices' && <label>Due date<input name="due_date" type="date" defaultValue={record?.due_date} /></label>}
          {linked && <label>Purchase order<select required value={poId} onChange={e => selectPO(e.target.value)}><option value="">Select an order</option>{orders.map(o => <option key={o.id} value={o.id}>{o.number}</option>)}</select></label>}
          <label>Supplier<select required disabled={linked} value={supplierId} onChange={e => setSupplierId(e.target.value)}><option value="">Select a supplier</option>{suppliers.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
          {!receipt && <label>Currency (ISO code)<input required minLength={3} maxLength={3} value={currency} readOnly={linked} onChange={e => setCurrency(e.target.value.toUpperCase())} /></label>}
          {resource === 'invoices' && <><label>Subtotal<input name="subtotal" type="number" min="0" step="0.01" defaultValue={record?.subtotal} /></label><label>Discount<input name="discount" type="number" min="0" step="0.01" defaultValue={record?.discount} /></label><label>VAT amount<input name="vat_amount" type="number" min="0" step="0.01" defaultValue={record?.vat_amount} /></label><label>Grand total<input name="grand_total" type="number" min="0" step="0.01" defaultValue={record?.grand_total} /></label></>}
        </div>
        <div className="border-t border-slate-100 pt-5"><div className="flex items-center justify-between mb-4"><h3 className="font-semibold">Line items</h3><span className="text-xs text-slate-400">Amounts exclude VAT</span></div>
          <div className="space-y-3">{lines.map((line, index) => <div key={index} className="grid grid-cols-12 items-end gap-3 bg-slate-50 p-3 rounded-lg">
            <label className="col-span-12 sm:col-span-5">Description{linked ? <select aria-label={`PO line ${index + 1}`} required value={line.purchase_order_line_id || ''} onChange={e => {
              const selected = po?.lines?.find(l => l.id === e.target.value);
              setLines(lines.map((l, i) => i === index ? { ...l, purchase_order_line_id: selected?.id, description: selected?.description || '' } : l));
            }}><option value="">Select PO line</option>{po?.lines?.map(l => <option key={l.id} value={l.id}>{l.description}</option>)}</select> : <input aria-label={`Description ${index + 1}`} required maxLength={500} value={line.description} onChange={e => updateLine(index, 'description', e.target.value)} />}</label>
            <label className="col-span-5 sm:col-span-3">Quantity<input aria-label={`Quantity ${index + 1}`} type="number" min="0.001" step="0.001" required value={line.quantity} onChange={e => updateLine(index, 'quantity', e.target.value)} /></label>
            {!receipt && <label className="col-span-5 sm:col-span-3">Unit price<input aria-label={`Unit price ${index + 1}`} type="number" min="0" step="0.01" required value={line.unit_price} onChange={e => updateLine(index, 'unit_price', e.target.value)} /></label>}
            <Button type="button" variant="ghost" className="col-span-2 sm:col-span-1 px-2" disabled={lines.length === 1} onClick={() => setLines(lines.filter((_, i) => i !== index))} aria-label={`Remove line ${index + 1}`}><Trash2 size={16} /></Button>
          </div>)}</div>
          <Button type="button" variant="outline" size="sm" className="mt-4" disabled={lines.length >= 200 || (linked && !po)} onClick={() => setLines([...lines, { description: '', quantity: '1', unit_price: '0.00', ...(linked ? { purchase_order_line_id: '' } : {}) }])}><Plus size={14} />Add line</Button>
        </div>
        <label>Notes<textarea name="notes" maxLength={2000} rows={2} defaultValue={record?.notes} /></label>
      </>}
      {error && <p role="alert" className="text-red-700 bg-red-50 p-3 rounded-lg">{error}</p>}
    </div><div className="flex justify-end gap-3 bg-slate-50 p-5 border-t border-slate-100"><Button type="button" variant="outline" onClick={onClose}>Cancel</Button><Button disabled={busy || (!supplier && lines.length === 0)}>{busy ? 'Saving…' : 'Save ' + title}</Button></div>
  </form></dialog>;
}
