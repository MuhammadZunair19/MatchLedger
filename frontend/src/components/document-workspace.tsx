'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { UploadCloud, FileText, Search, ArrowRight, Trash2, RefreshCw, CheckCircle2 } from 'lucide-react';
import { Auth, api } from '@/lib/api';
import { DocumentRow, documentTypes, statuses, pretty, uploadDocument } from '@/lib/documents';
import { Button } from './ui/button';
import DocumentReview from './document-review';

export function StatusBadge({ value }: { value: string }) {
  const color = value === 'VERIFIED' ? 'bg-teal-50 text-teal-800' : value === 'FAILED' ? 'bg-red-50 text-red-700' : value === 'REVIEW_REQUIRED' ? 'bg-amber-50 text-amber-800' : 'bg-slate-100 text-slate-600';
  return <span className={`inline-flex px-2.5 py-1 rounded-full text-[10px] font-semibold tracking-wide ${color}`}>{pretty(value)}</span>;
}

export default function DocumentWorkspace({ auth }: { auth: Auth }) {
  const path = usePathname(); const router = useRouter();
  const parts = path.split('/').filter(Boolean); const id = parts[1] && parts[1] !== 'upload' ? parts[1] : null;
  const uploading = parts[1] === 'upload';
  const [rows, setRows] = useState<DocumentRow[]>([]); const [total, setTotal] = useState(0); const [page, setPage] = useState(1);
  const [query, setQuery] = useState(''); const [search, setSearch] = useState(''); const [status, setStatus] = useState(''); const [kind, setKind] = useState('');
  const [loading, setLoading] = useState(true); const [error, setError] = useState(''); const [version, setVersion] = useState(0); const [deleting, setDeleting] = useState<string | null>(null);
  const [uploadKind, setUploadKind] = useState('purchase_order'); const [drag, setDrag] = useState(false); const [busy, setBusy] = useState(false);
  const [uploads, setUploads] = useState<{ name: string; progress: number; error?: string; id?: string }[]>([]); const fileInput = useRef<HTMLInputElement>(null);
  const reload = useCallback(async (signal?: AbortSignal) => {
    const result = await api<{ items: DocumentRow[]; total: number }>(`/documents?page=${page}&q=${encodeURIComponent(search)}&${status ? `status=${status}&` : ''}${kind ? `document_type=${kind}` : ''}`, { signal });
    setRows(result.items); setTotal(result.total);
  }, [page, search, status, kind]);
  useEffect(() => {
    if (id) return;
    const controller = new AbortController(); setLoading(true);
    reload(controller.signal).catch(e => { if (e.name !== 'AbortError') setError(e.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [id, reload, version]);
  useEffect(() => {
    if (!rows.some(row => ['QUEUED', 'PROCESSING'].includes(row.status)) || id) return;
    const timer = setInterval(() => reload().catch(e => setError(e.message)), 3000); return () => clearInterval(timer);
  }, [rows, id, reload]);
  async function upload(files: FileList | File[]) {
    if (busy) return;
    const selected = Array.from(files); if (!selected.length) return;
    setBusy(true); setError(''); setUploads(selected.map(file => ({ name: file.name, progress: 0 })));
    for (const [index, file] of selected.entries()) {
      try {
        const doc = await uploadDocument(file, uploadKind, auth.csrf_token, progress => setUploads(current => current.map((u, i) => i === index ? { ...u, progress } : u)));
        setUploads(current => current.map((u, i) => i === index ? { ...u, id: doc.id, progress: 100 } : u));
      } catch (e) { setUploads(current => current.map((u, i) => i === index ? { ...u, error: (e as Error).message } : u)); }
    }
    setBusy(false); setVersion(v => v + 1); if (fileInput.current) fileInput.current.value = '';
  }
  async function remove(documentId: string) {
    setBusy(true); setError('');
    try { await api(`/documents/${documentId}`, { method: 'DELETE' }, auth.csrf_token); setDeleting(null); setVersion(v => v + 1); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  if (id) return <DocumentReview key={`${auth.organization_id}-${id}`} id={id} auth={auth} />;
  return <div className="space-y-6">
    <div className="flex justify-between gap-4 items-center"><p className="text-slate-500">Private documents. Traceable extraction. Human-verified records.</p>{!uploading && <Button asChild><Link href="/documents/upload"><UploadCloud size={16} />Upload documents</Link></Button>}</div>
    {error && <p role="alert" className="p-4 rounded-lg bg-red-50 text-red-700">{error}</p>}
    {uploading && <section className="card p-6"><div className="flex gap-5 flex-wrap items-end mb-5"><label className="min-w-56">Document type<select aria-label="Document type" value={uploadKind} disabled={busy} onChange={e => setUploadKind(e.target.value)}>{Object.entries(documentTypes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><p className="text-xs text-slate-400">All files in this batch use the selected document type.</p></div>
      <div className={`border-2 border-dashed rounded-xl p-10 text-center transition ${drag ? 'border-teal-500 bg-teal-50' : 'border-slate-200 bg-slate-50'}`} onDragOver={e => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={e => { e.preventDefault(); setDrag(false); void upload(e.dataTransfer.files); }}>
        <UploadCloud size={34} className="mx-auto text-teal-700 mb-4" /><h2 className="font-semibold text-lg">Drop your procurement documents here</h2><p className="text-sm text-slate-500 mt-2 mb-5">PDF, JPG or PNG · limits are validated by the server</p><Button disabled={busy} onClick={() => fileInput.current?.click()}>Choose files</Button><input ref={fileInput} type="file" aria-label="Upload files" className="sr-only" accept=".pdf,.jpg,.jpeg,.png" multiple onChange={e => e.target.files && void upload(e.target.files)} /></div>
      <div className="space-y-3 mt-5">{uploads.map((item, i) => <div key={i} className="p-3 border border-slate-200 rounded-lg"><div className="flex justify-between items-center gap-3"><span className="text-sm truncate">{item.name}</span>{item.id ? <Link href={`/documents/${item.id}/review`} className="text-teal-700 text-xs font-semibold flex gap-1 items-center">Open document<ArrowRight size={14} /></Link> : <span className="text-xs text-slate-500">{item.error ? 'Failed' : item.progress === 100 ? 'Validating…' : `${item.progress}%`}</span>}</div><progress className="w-full h-1.5 accent-teal-700 mt-3" max="100" value={item.progress} />{item.error && <p role="alert" className="text-xs text-red-700 mt-2">{item.error}</p>}{item.id && <p role="status" className="text-xs text-teal-700 mt-2">Uploaded and validated. Open the document to start extraction.</p>}</div>)}</div>
    </section>}
    <section className="card overflow-hidden"><div className="p-5 flex justify-between flex-wrap gap-4"><h2 className="font-semibold self-center">Document history <span className="text-slate-400 text-xs ml-2">{total} files</span></h2><form className="flex flex-wrap gap-2" onSubmit={e => { e.preventDefault(); setSearch(query); setPage(1); }}><input className="!w-44 !text-xs" aria-label="Search documents" placeholder="Search filename" value={query} onChange={e => setQuery(e.target.value)} /><select className="!w-36 !text-xs" aria-label="Filter status" value={status} onChange={e => { setStatus(e.target.value); setPage(1); }}><option value="">All statuses</option>{statuses.map(s => <option key={s}>{s}</option>)}</select><select className="!w-40 !text-xs" aria-label="Filter document type" value={kind} onChange={e => { setKind(e.target.value); setPage(1); }}><option value="">All types</option>{Object.entries(documentTypes).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select><Button variant="outline" aria-label="Search"><Search size={15} /></Button></form></div>
      {loading ? <div role="status" className="p-6 animate-pulse space-y-4">{[1, 2, 3].map(n => <div key={n} className="h-10 bg-slate-100 rounded" />)}<span className="sr-only">Loading documents</span></div> : <><div className="overflow-auto"><table><thead><tr><th>Document</th><th>Supplier</th><th>Uploaded</th><th>Status</th><th>Actions</th></tr></thead><tbody>{rows.map(row => <tr key={row.id}><td><Link className="font-semibold text-teal-800 flex items-center gap-2" href={`/documents/${row.id}/review`}><FileText size={16} />{row.filename}</Link><span className="text-[11px] text-slate-400 block mt-1">{documentTypes[row.document_type]} · {row.page_count} page(s)</span></td><td>{row.supplier_name || 'Not reviewed'}</td><td className="text-xs text-slate-500">{new Date(row.created_at).toLocaleDateString()}</td><td><StatusBadge value={row.status} /></td><td><div className="flex gap-2">{deleting === row.id ? <><Button size="sm" variant="destructive" disabled={busy} onClick={() => remove(row.id)}>Confirm delete</Button><Button size="sm" variant="ghost" onClick={() => setDeleting(null)}>Cancel</Button></> : <><Button size="sm" variant="outline" asChild><Link href={`/documents/${row.id}/review`}>Open</Link></Button><Button size="sm" variant="ghost" aria-label={`Delete ${row.filename}`} onClick={() => setDeleting(row.id)} disabled={['QUEUED', 'PROCESSING'].includes(row.status)}><Trash2 size={14} /></Button></>}</div></td></tr>)}</tbody></table></div>{rows.length === 0 && <div className="p-14 text-center"><FileText className="mx-auto text-slate-300 mb-4" size={30} /><h3 className="font-semibold">No documents yet</h3><p className="text-slate-500 mt-2">Upload a purchase order, supplier invoice or delivery note.</p></div>}</>}
      <div className="flex justify-between p-4 border-t border-slate-100 text-xs items-center"><span className="text-slate-400">Page {page} of {Math.max(1, Math.ceil(total/20))}</span><div className="flex gap-2"><Button variant="outline" size="sm" disabled={page === 1} onClick={() => setPage(page-1)}>Previous</Button><Button variant="outline" size="sm" disabled={page*20 >= total} onClick={() => setPage(page+1)}>Next</Button></div></div>
    </section>
  </div>;
}
