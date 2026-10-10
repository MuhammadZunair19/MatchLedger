'use client';
import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, Download, ScanText, Save, CheckCircle2, Plus, Trash2, Crosshair, ZoomIn, ZoomOut, ChevronLeft, ChevronRight } from 'lucide-react';
import { Auth, RecordRow, api, allRecords } from '@/lib/api';
import { DocumentRow, Evidence, ExtractionResponse, ReviewData, ReviewLine, documentTypes, pretty } from '@/lib/documents';
import { Button } from './ui/button';

export default function DocumentReview({ id, auth }: { id: string; auth: Auth }) {
  const [doc, setDoc] = useState<DocumentRow | null>(null); const [extraction, setExtraction] = useState<ExtractionResponse | null>(null);
  const [draft, setDraft] = useState<ReviewData | null>(null); const [revision, setRevision] = useState(0); const [dirty, setDirty] = useState(false);
  const [suppliers, setSuppliers] = useState<RecordRow[]>([]); const [orders, setOrders] = useState<RecordRow[]>([]);
  const [error, setError] = useState(''); const [notice, setNotice] = useState(''); const [busy, setBusy] = useState(false);
  const [page, setPage] = useState(1); const [zoom, setZoom] = useState(100); const [highlight, setHighlight] = useState<number[] | null>(null);
  const [ack, setAck] = useState(false); const [createSupplier, setCreateSupplier] = useState(false); const [historyVersion, setHistoryVersion] = useState('');
  const [corrections, setCorrections] = useState<{ id: string; field_path: string; created_by: string; created_at: string; revision: number }[]>([]);
  const load = useCallback(async (reset = true) => {
    const [document, data] = await Promise.all([api<DocumentRow>(`/documents/${id}`), api<ExtractionResponse>(`/documents/${id}/extraction`)]);
    setDoc(document); setExtraction(data);
    if (reset) { setDraft(data.review_data); setRevision(data.review_revision); setDirty(false); }
  }, [id]);
  useEffect(() => { load().catch(e => setError(e.message)); Promise.all([allRecords('suppliers'), allRecords('purchase-orders')]).then(([s, o]) => { setSuppliers(s); setOrders(o); }).catch(e => setError(e.message)); }, [load]);
  useEffect(() => {
    if (!doc || !['QUEUED', 'PROCESSING'].includes(doc.status)) return;
    const timer = setInterval(() => load(!dirty).catch(e => setError(e.message)), 2500); return () => clearInterval(timer);
  }, [doc, dirty, load]);
  async function start() {
    setBusy(true); setError(''); setNotice('');
    try { await api(`/documents/${id}/extract`, { method: 'POST' }, auth.csrf_token); await load(!dirty); }
    catch (e) { setError((e as Error).message); await load(!dirty).catch(() => {}); } finally { setBusy(false); }
  }
  async function save() {
    if (!draft) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await api<{ review_revision: number; review_data: ReviewData; validation_warnings: string[] }>(`/documents/${id}/review`, { method: 'PUT', body: JSON.stringify({ revision, data: draft }) }, auth.csrf_token);
      setRevision(result.review_revision); setDraft(result.review_data); setDirty(false); setNotice('Draft saved. Your corrections are recorded.');
      setExtraction(current => current ? { ...current, validation_warnings: result.validation_warnings } : current);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function confirm() {
    setBusy(true); setError(''); setNotice('');
    try { await api(`/documents/${id}/verify`, { method: 'POST', body: JSON.stringify({ revision, acknowledge_warnings: ack, create_supplier: createSupplier }) }, auth.csrf_token); await load(); setNotice('Verified. A new procurement record was created.'); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  function editField(key: string, value: string) { if (!draft) return; setDraft({ ...draft, fields: { ...draft.fields, [key]: value || null } }); setDirty(true); }
  function editLine(index: number, key: string, value: string) { if (!draft) return; setDraft({ ...draft, lines: draft.lines.map((line, i) => i === index ? { ...line, [key]: value || null } : line) }); setDirty(true); }
  function source(evidence?: Evidence) { if (!evidence?.page_number) return; setPage(evidence.page_number); setHighlight(evidence.bounding_box); }
  async function history(version: string) { setHistoryVersion(version); try { const value = await api<ExtractionResponse>(`/documents/${id}/extraction${version ? `?version=${version}` : ''}`); setExtraction(current => current ? { ...current, latest: value.latest } : value); } catch (e) { setError((e as Error).message); } }
  if (!doc) return <div role={error ? 'alert' : 'status'} className="card p-8">{error || 'Loading document…'}</div>;
  const processing = ['QUEUED', 'PROCESSING'].includes(doc.status); const verified = doc.status === 'VERIFIED';
  const evidence = extraction?.latest?.extracted_data;
  const po = orders.find(order => order.id === draft?.purchase_order_id);
  const required = ['number', 'date', 'supplier_name', ...(doc.document_type !== 'goods_receipt' ? ['currency'] : [])];
  return <div className="space-y-5">
    <div className="flex flex-wrap justify-between gap-3 items-center"><Link href="/documents" className="text-xs font-semibold text-teal-700 flex items-center gap-2"><ArrowLeft size={14} />All documents</Link><div className="flex gap-2"><Button variant="outline" size="sm" asChild><a href={`/api/documents/${id}/file`}><Download size={14} />Download original</a></Button>{!verified && <Button size="sm" disabled={busy || processing || dirty} onClick={start}><ScanText size={14} />{processing ? 'Processing…' : extraction?.latest ? 'Retry extraction' : 'Start extraction'}</Button>}</div></div>
    <div className="flex gap-3 items-center"><h2 className="text-lg font-semibold break-all">{doc.filename}</h2><span className="text-xs rounded-full bg-teal-50 text-teal-800 px-3 py-1" role="status">{pretty(doc.status)}</span></div>
    <p className="text-xs text-slate-500">{documentTypes[doc.document_type]} · {doc.page_count} page(s) · Original files stay private to this organization.</p>
    {error && <p role="alert" className="rounded-lg bg-red-50 text-red-700 p-4">{error}</p>}{doc.last_error && <p role="alert" className="rounded-lg bg-red-50 text-red-700 p-4">{doc.last_error}</p>}{notice && <p role="status" className="rounded-lg bg-teal-50 text-teal-800 p-4">{notice}</p>}
    {processing && <p className="p-4 rounded-lg bg-sky-50 text-sky-800">The background worker is processing this document. You can leave this page; progress is saved.</p>}
    {verified && <div className="card p-4 text-teal-800 flex items-center gap-3"><CheckCircle2 size={20} /><div><strong>Verified and saved</strong><p className="text-xs mt-1">{doc.business_entity_type} · {doc.business_entity_id}</p></div></div>}
    <div className="grid xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)] gap-5 items-start">
      <section className="card overflow-hidden xl:sticky xl:top-5"><div className="p-3 border-b border-slate-200 flex flex-wrap justify-between gap-2 items-center"><div className="flex items-center gap-1"><Button variant="ghost" size="sm" aria-label="Previous document page" disabled={page <= 1} onClick={() => { setPage(page-1); setHighlight(null); }}><ChevronLeft size={15} /></Button><span className="text-xs">Page {page} / {doc.page_count}</span><Button variant="ghost" size="sm" aria-label="Next document page" disabled={page >= doc.page_count} onClick={() => { setPage(page+1); setHighlight(null); }}><ChevronRight size={15} /></Button></div><div className="flex gap-1 items-center"><Button variant="ghost" size="sm" disabled={zoom <= 50} onClick={() => setZoom(zoom-25)} aria-label="Zoom out"><ZoomOut size={15} /></Button><span className="text-xs">{zoom}%</span><Button variant="ghost" size="sm" disabled={zoom >= 200} onClick={() => setZoom(zoom+25)} aria-label="Zoom in"><ZoomIn size={15} /></Button></div></div><div className="overflow-auto bg-slate-200 p-3 max-h-[78vh]"><div className="relative bg-white mx-auto" style={{ width: `${zoom}%`, minWidth: `${zoom}%` }}>
        {/* Authenticated raster preview: no embedded PDF scripts or public URLs. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={`/api/documents/${id}/pages/${page}`} alt={`Original document page ${page}`} className="w-full h-auto block" onError={() => setError('The document preview could not be loaded. Try reloading the page.')} />
        {highlight && <div className="absolute border-2 border-amber-500 bg-amber-300/25 pointer-events-none" style={{ left: `${highlight[0]*100}%`, top: `${highlight[1]*100}%`, width: `${(highlight[2]-highlight[0])*100}%`, height: `${(highlight[3]-highlight[1])*100}%` }} />}
      </div></div><p className="text-[11px] text-slate-400 p-3">Click a source marker beside a field to locate its evidence.</p></section>
      <section className="card p-5 space-y-6 min-w-0">
        <div><h3 className="font-semibold text-lg">Review extracted data</h3><p className="text-xs leading-5 text-slate-500 mt-1">Check every field against the source. Missing values stay empty; nothing is inferred as an authoritative financial record.</p></div>
        {!draft ? <div className="bg-slate-50 rounded-lg p-7 text-center text-slate-500"><ScanText className="mx-auto mb-3" size={26} /><p>{processing ? 'Waiting for extraction results…' : 'Start extraction to prepare a review draft.'}</p></div> : <>
          {extraction?.latest?.warnings.length ? <details className="bg-amber-50 text-amber-900 p-3 rounded-lg"><summary className="text-xs font-semibold cursor-pointer">Extraction warnings ({extraction.latest.warnings.length})</summary><ul className="list-disc ml-4 mt-2 text-xs space-y-1">{extraction.latest.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul></details> : null}
          <fieldset disabled={verified || busy || processing} className="space-y-5 min-w-0">
            <div className="grid sm:grid-cols-2 gap-4">{Object.entries(draft.fields).map(([key, value]) => {
              const item = evidence?.fields[key]; const missing = required.includes(key) && !value;
              return <div key={key}><div className="flex gap-2 justify-between items-center"><label htmlFor={`field-${key}`}>{pretty(key)}{required.includes(key) ? ' *' : ''}</label>{item?.page_number && <button type="button" className="text-teal-700 flex items-center gap-1 text-[10px]" onClick={() => source(item)} title={`Source: ${item.extraction_method}`} aria-label={`Show source for ${pretty(key)}`}><Crosshair size={12} />p.{item.page_number}</button>}</div><input id={`field-${key}`} dir="auto" value={value || ''} onChange={e => editField(key, e.target.value)} className={`mt-1 !text-sm ${missing ? '!border-amber-400 !bg-amber-50' : ''}`} placeholder={missing ? 'Required — enter from source' : 'Not found in document'} />{item && <p className="text-[10px] text-slate-400 mt-1">{item.confidence != null ? `OCR ${Math.round(item.confidence*100)}% · ` : ''}{item.uncertainty || (item.original_value != null ? 'Source available · verify value' : 'Missing from extraction')}</p>}</div>;
            })}</div>
            <div className="border-t border-slate-100 pt-5 space-y-4"><h4 className="font-semibold">Link to your ledger</h4><label>Existing supplier<select aria-label="Existing supplier" value={draft.supplier_id || ''} onChange={e => { setDraft({ ...draft, supplier_id: e.target.value || null }); setDirty(true); }}><option value="">Select supplier</option>{suppliers.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
              {!draft.supplier_id && <label className="flex gap-2 items-center font-normal"><input type="checkbox" className="!w-auto" checked={createSupplier} onChange={e => setCreateSupplier(e.target.checked)} />Create a supplier using the reviewed supplier name on confirmation</label>}
              {doc.document_type !== 'purchase_order' && <label>Linked purchase order<select aria-label="Linked purchase order" value={draft.purchase_order_id || ''} onChange={e => { const selected = orders.find(o => o.id === e.target.value); setDraft({ ...draft, purchase_order_id: selected?.id || null, supplier_id: selected?.supplier_id || draft.supplier_id, lines: draft.lines.map(line => ({ ...line, purchase_order_line_id: null })) }); setDirty(true); }}><option value="">Select the actual purchase order</option>{orders.map(order => <option key={order.id} value={order.id}>{order.number}</option>)}</select></label>}
            </div>
            <div className="border-t border-slate-100 pt-5"><div className="flex justify-between items-center mb-3"><h4 className="font-semibold">Line items</h4><Button variant="outline" size="sm" type="button" onClick={() => { setDraft({ ...draft, lines: [...draft.lines, { id: crypto.randomUUID(), description: null, quantity: null, unit_price: null, line_total: null, sku: null, unit_of_measure: null }] }); setDirty(true); }}><Plus size={14} />Add row</Button></div>
              <div className="space-y-4">{draft.lines.map((line, index) => <div key={line.id} className="bg-slate-50 border border-slate-100 rounded-lg p-3"><div className="flex justify-between mb-2"><span className="text-xs font-semibold">Line {index+1}</span><div className="flex gap-2"><button type="button" className="text-teal-700" aria-label={`Show source for line ${index+1}`} onClick={() => source(evidence?.lines.find(l => l.id === line.id)?.fields.description)}><Crosshair size={14} /></button><button type="button" className="text-slate-400" aria-label={`Remove row ${index+1}`} onClick={() => { setDraft({ ...draft, lines: draft.lines.filter((_, i) => i !== index) }); setDirty(true); }}><Trash2 size={14} /></button></div></div>
                <div className="grid grid-cols-2 gap-3">{(['description', 'sku', 'quantity', 'unit_of_measure', ...(doc.document_type !== 'goods_receipt' ? ['unit_price', 'line_total'] : [])] as (keyof ReviewLine)[]).map(key => <label key={key} className={key === 'description' ? 'col-span-2' : ''}>{pretty(key)}<input aria-label={`Line ${index+1} ${pretty(key)}`} dir="auto" value={line[key] || ''} onChange={e => editLine(index, key, e.target.value)} className="!text-xs" /></label>)}</div>
                {doc.document_type !== 'purchase_order' && <label className="mt-3">Source PO line<select aria-label={`Line ${index+1} Source PO line`} value={line.purchase_order_line_id || ''} onChange={e => editLine(index, 'purchase_order_line_id', e.target.value)}><option value="">Choose a PO line</option>{po?.lines?.map(l => <option key={l.id} value={l.id}>{l.description}</option>)}</select></label>}
              </div>)}</div>
            </div>
          </fieldset>
          {extraction?.validation_warnings.length ? <div className="rounded-lg bg-amber-50 p-3 text-xs text-amber-900"><p className="font-semibold mb-2">Review validation</p><ul className="list-disc ml-4 space-y-1">{extraction.validation_warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></div> : null}
          {!verified && <div className="border-t border-slate-100 pt-4"><label className="flex items-start gap-2 mb-4 font-normal"><input type="checkbox" className="!w-auto mt-0.5" checked={ack} onChange={e => setAck(e.target.checked)} />I checked the source and acknowledge any extraction or arithmetic warnings.</label><div className="flex flex-wrap gap-2"><Button variant="outline" disabled={busy || processing} onClick={save}><Save size={15} />Save draft</Button><Button disabled={busy || processing || dirty || !ack} onClick={confirm}><CheckCircle2 size={15} />Confirm extraction</Button></div><p className="text-[11px] text-slate-400 mt-3">{dirty ? 'Unsaved changes — save your draft before confirming.' : `Saved revision ${revision}. Confirmation creates a new business record.`}</p></div>}
        </>}
      </section>
    </div>
    <section className="card p-5"><h3 className="font-semibold mb-4">Extraction & correction history</h3><div className="flex flex-wrap gap-4 items-end"><label className="min-w-64">Evidence version<select aria-label="Evidence version" value={historyVersion} onChange={e => history(e.target.value)}><option value="">Latest extraction</option>{extraction?.history.map(run => <option key={run.id} value={run.version}>Version {run.version} · {pretty(run.status)}</option>)}</select></label><Button variant="outline" size="sm" onClick={() => api<typeof corrections>(`/documents/${id}/corrections`).then(setCorrections).catch(e => setError(e.message))}>Load correction history</Button></div><p className="text-xs text-slate-400 mt-3">Changing the evidence version never replaces your saved corrections.</p>{extraction?.latest && <p className="text-xs text-slate-500 mt-3">{extraction.latest.engine} · {extraction.latest.completed_at ? new Date(extraction.latest.completed_at).toLocaleString() : 'Not completed'}{extraction.latest.error && ` · ${extraction.latest.error}`}</p>}{corrections.map(c => <p key={c.id} className="text-xs border-t border-slate-100 pt-2 mt-2">Revision {c.revision} · {c.field_path} · {new Date(c.created_at).toLocaleString()} · User {c.created_by}</p>)}</section>
  </div>;
}
