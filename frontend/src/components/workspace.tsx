'use client';
import { useEffect, useState } from 'react';
import { LayoutDashboard, Building2, ClipboardList, PackageCheck, ReceiptText, Layers3, Users, LogOut, Plus, Search, ArrowUpRight, ChevronLeft, ChevronRight, Pencil, Trash2, Menu, X, CheckCircle2 } from 'lucide-react';
import { api, Auth, Page, RecordRow, money, allRecords } from '@/lib/api';
import { Button } from './ui/button';
import AuthForm from './auth-form';
import RecordEditor from './record-editor';
import DocumentWorkspace from './document-workspace';
import { useRouter } from 'next/navigation';

const navigation = [
  { id: 'dashboard', label: 'Overview', icon: LayoutDashboard },
  { id: 'suppliers', label: 'Suppliers', icon: Building2 },
  { id: 'purchase-orders', label: 'Purchase orders', icon: ClipboardList },
  { id: 'receipts', label: 'Goods receipts', icon: PackageCheck },
  { id: 'invoices', label: 'Supplier invoices', icon: ReceiptText },
  { id: 'documents', label: 'Documents', icon: Layers3 },
  { id: 'members', label: 'Team members', icon: Users },
];
type Dashboard = { counts: { [key: string]: number }; invoice_totals: { [key: string]: string }; activity: { id: string; action: string; entity_type: string; created_at: string }[] };
type Member = { id: string; name: string; email: string; role: string };

export default function Workspace({ initialScreen = 'dashboard' }: { initialScreen?: string }) {
  const router = useRouter();
  const [auth, setAuth] = useState<Auth | null>(null); const [initializing, setInitializing] = useState(true);
  const [screen, setScreen] = useState(initialScreen); const [mobile, setMobile] = useState(false);
  const [data, setData] = useState<Page | null>(null); const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [suppliers, setSuppliers] = useState<RecordRow[]>([]); const [orders, setOrders] = useState<RecordRow[]>([]);
  const [members, setMembers] = useState<Member[]>([]); const [query, setQuery] = useState(''); const [search, setSearch] = useState(''); const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false); const [error, setError] = useState(''); const [notice, setNotice] = useState(''); const [version, setVersion] = useState(0);
  const [editor, setEditor] = useState<{ record: RecordRow | null } | null>(null); const [deleting, setDeleting] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  useEffect(() => { api<Auth>('/auth/me').then(setAuth).catch(() => {}).finally(() => setInitializing(false)); }, []);
  useEffect(() => {
    if (!auth) return;
    let active = true; setLoading(true); setError(''); setData(null); setDashboard(null); setMembers([]);
    const load = async () => {
      if (screen === 'documents') return;
      if (screen === 'dashboard') { const value = await api<Dashboard>('/dashboard'); if (active) setDashboard(value); }
      else if (screen === 'members') { const value = await api<Member[]>('/members'); if (active) setMembers(value); }
      else {
        const [records, supplierRows, orderRows] = await Promise.all([api<Page>(`/${screen}?page=${page}&page_size=10&q=${encodeURIComponent(search)}`), allRecords('suppliers'), screen === 'receipts' || screen === 'invoices' ? allRecords('purchase-orders') : Promise.resolve([])]);
        if (active) { setData(records); setSuppliers(supplierRows); setOrders(orderRows); }
      }
    };
    load().catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [auth, screen, page, search, version]);
  function navigate(id: string) { if (id === 'documents') router.push('/documents'); setScreen(id); setPage(1); setSearch(''); setQuery(''); setNotice(''); setDeleting(null); setMobile(false); }
  async function logout() { setBusy(true); try { await api('/auth/logout', { method: 'POST' }, auth?.csrf_token); setAuth(null); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }
  async function remove(id: string) {
    setBusy(true); setError('');
    try { await api(`/${screen}/${id}`, { method: 'DELETE' }, auth?.csrf_token); setDeleting(null); setNotice('Record deleted.'); setPage(1); setVersion(v => v + 1); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function addMember(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; setBusy(true); setError('');
    try { await api('/members', { method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(form))) }, auth?.csrf_token); form.reset(); setVersion(v => v + 1); setNotice('Member added.'); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  if (initializing) return <div className="p-16 text-slate-500">Opening your workspace…</div>;
  if (!auth) return <AuthForm onAuth={a => { setAuth(a); navigate('dashboard'); }} />;
  const org = auth.organizations.find(o => o.id === auth.organization_id)!;
  const title = navigation.find(n => n.id === screen)?.label;
  const isResource = !['dashboard', 'members', 'documents'].includes(screen);
  return <div className="min-h-screen lg:pl-64">
    <aside className={`${mobile ? 'flex' : 'hidden'} lg:flex fixed inset-y-0 left-0 w-64 z-30 bg-[#132d3d] text-slate-300 flex-col p-5 overflow-y-auto`}>
      <div className="flex items-center gap-2.5 text-xl text-white font-bold px-2 pt-3 pb-10"><Layers3 className="text-teal-300" size={25} />MatchLedger<span className="text-teal-300 -ml-2">.</span><button className="lg:hidden ml-auto" onClick={() => setMobile(false)} aria-label="Close navigation"><X size={18} /></button></div>
      <label className="text-slate-400 text-[10px] uppercase tracking-widest px-2">Workspace<select className="!bg-[#203c4d] !text-white !border-slate-600 !text-xs mb-8" aria-label="Organization" value={auth.organization_id} onChange={async e => {
        setError(''); try { const next = await api<Auth>('/auth/organization', { method: 'POST', body: JSON.stringify({ organization_id: e.target.value }) }, auth.csrf_token); setEditor(null); setAuth(next); navigate('dashboard'); } catch (err) { setError((err as Error).message); }
      }}>{auth.organizations.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}</select></label>
      <p className="eyebrow text-slate-500 px-3 mb-3">Procurement</p><nav className="space-y-1">{navigation.map(({ id, label, icon: Icon }) => <button key={id} onClick={() => navigate(id)} className={`w-full flex items-center gap-3 rounded-lg px-3 py-3 text-[13px] text-left transition ${screen === id ? 'bg-teal-400/15 text-teal-200 font-semibold' : 'hover:bg-white/5'}`} aria-current={screen === id ? 'page' : undefined}><Icon size={18} />{label}{screen === id && <span className="ml-auto w-1.5 h-1.5 rounded-full bg-teal-300" />}</button>)}</nav>
      <div className="mt-auto pt-12"><div className="sidebar-tip rounded-lg border border-slate-600/50 p-4 mb-5"><p className="text-teal-200 text-xs font-semibold">A foundation for better matching</p><p className="text-xs text-slate-400 leading-5 mt-2">Capture records now. Automated matching arrives in a later milestone.</p></div><div className="border-t border-slate-600/50 pt-5 flex items-center gap-3"><div className="rounded-full bg-slate-600 text-white w-9 h-9 flex items-center justify-center">{auth.user.name.slice(0, 1).toUpperCase()}</div><div className="min-w-0"><p className="text-xs text-white truncate">{auth.user.name}</p><p className="text-[11px] mt-1 capitalize text-slate-400">{org.role}</p></div><button onClick={logout} disabled={busy} aria-label="Sign out" className="ml-auto hover:text-white"><LogOut size={17} /></button></div></div>
    </aside>
    <header className="bg-white border-b border-slate-200 h-18 px-6 lg:px-10 flex items-center justify-between"><div className="flex gap-3 items-center"><button className="lg:hidden" onClick={() => setMobile(true)} aria-label="Open navigation"><Menu size={22} /></button><span className="text-slate-400 text-xs">Workspace</span><span className="text-slate-300">/</span><span className="text-xs font-semibold">{title}</span></div><span className="flex gap-2 items-center text-[11px] text-slate-500"><span className="w-1.5 h-1.5 bg-teal-600 rounded-full" />Milestone 2</span></header>
    <main className="p-6 lg:p-10 max-w-[1500px] mx-auto">
      <div className="flex flex-wrap gap-4 justify-between items-end mb-8"><div><p className="eyebrow text-teal-700 mb-3">{org.name}</p><h1 className="text-3xl font-semibold tracking-tight">{screen === 'dashboard' ? 'Procurement overview' : title}</h1><p className="text-slate-500 mt-2 text-sm">{screen === 'dashboard' ? 'A clear picture of your procurement, from order to invoice.' : screen === 'members' ? 'Manage the people who share your organization’s ledger.' : 'Organize, review and maintain your procurement records.'}</p></div>{isResource && <Button disabled={loading || !data} onClick={() => setEditor({ record: null })}><Plus size={16} />New {screen === 'suppliers' ? 'supplier' : screen === 'purchase-orders' ? 'purchase order' : screen === 'receipts' ? 'receipt' : 'invoice'}</Button>}</div>
      {error && <div role="alert" className="p-4 bg-red-50 border border-red-100 rounded-lg text-red-700 mb-5">{error}<Button variant="ghost" size="sm" className="ml-3" onClick={() => setVersion(v => v + 1)}>Retry</Button></div>}
      {notice && <p role="status" className="p-3 mb-5 rounded-lg bg-teal-50 text-teal-800 flex gap-2 items-center"><CheckCircle2 size={16} />{notice}</p>}
      {loading && <p role="status" className="py-12 text-slate-500">Loading your records…</p>}
      {screen === 'documents' && <DocumentWorkspace key={auth.organization_id} auth={auth} />}
      {!loading && dashboard && screen === 'dashboard' && <>
        <div className="grid sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-7">{navigation.slice(1, 5).map(({ id, label, icon: Icon }) => <button key={id} onClick={() => navigate(id)} className="card p-5 text-left hover:border-teal-500 transition"><div className="flex justify-between items-center"><span className="text-xs text-slate-500">{label}</span><Icon className="text-teal-700 bg-teal-50 rounded-lg p-2" size={36} /></div><div className="text-3xl font-semibold mt-3">{dashboard.counts[id]}</div><p className="text-[11px] text-slate-400 mt-4 flex items-center justify-between">View records<ArrowUpRight size={14} /></p></button>)}</div>
        <div className="grid xl:grid-cols-3 gap-6"><section className="card xl:col-span-2 overflow-hidden"><div className="p-6 border-b border-slate-100 flex justify-between items-center"><div><h2 className="font-semibold">Recent activity</h2><p className="text-xs text-slate-400 mt-1">The latest changes in your organization</p></div><span className="eyebrow text-slate-400">Audit trail</span></div>{dashboard.activity.length ? dashboard.activity.map(event => <div key={event.id} className="px-6 py-4 flex items-center gap-4 border-b last:border-b-0 border-slate-100"><div className="bg-slate-100 rounded-full p-2 text-slate-500"><ClipboardList size={16} /></div><div><p className="text-sm capitalize">{event.action.replaceAll('_', ' ')} · {event.entity_type.replaceAll('_', ' ')}</p><p className="text-xs text-slate-400 mt-1">{new Date(event.created_at).toLocaleString()}</p></div></div>) : <p className="p-8 text-slate-500">Your activity will appear as you add records.</p>}</section>
        <div className="space-y-6"><section className="card p-6"><p className="eyebrow text-slate-400 mb-4">Invoice value · excluding VAT</p>{Object.entries(dashboard.invoice_totals).length ? Object.entries(dashboard.invoice_totals).map(([currency, total]) => <p key={currency} className="text-2xl font-semibold mb-2">{money(total, currency)}</p>) : <p className="text-slate-500">No invoices recorded yet.</p>}<p className="text-xs leading-5 text-slate-400 mt-4">Totals are grouped by currency. No exchange-rate conversions are applied.</p><Button variant="outline" className="mt-5 w-full" onClick={() => navigate('invoices')}>View invoices<ArrowUpRight size={14} /></Button></section>
        <section className="rounded-xl bg-[#e8f2ee] p-6 border border-teal-100"><PackageCheck className="text-teal-700 mb-4" size={25} /><h2 className="font-semibold">Start with the source records</h2><p className="text-xs text-slate-600 leading-6 mt-2">Add a supplier, create a purchase order, then record deliveries and invoices against its lines.</p><button className="mt-4 text-xs font-semibold text-teal-800 flex gap-2 items-center" onClick={() => navigate('purchase-orders')}>Open purchase orders<ArrowUpRight size={14} /></button></section></div></div>
      </>}
      {isResource && <section className="card overflow-hidden"><div className="p-5 flex flex-wrap gap-3 justify-between items-center"><h2 className="font-semibold">All {title?.toLowerCase()} <span className="ml-2 text-xs text-slate-400 font-normal">{data?.total ?? '—'} records</span></h2><form className="flex gap-2" onSubmit={e => { e.preventDefault(); setSearch(query); setPage(1); }}><div className="relative"><Search size={15} className="absolute top-3 left-3 text-slate-400" /><input aria-label="Search records" value={query} onChange={e => setQuery(e.target.value)} className="!pl-9 !py-2 !text-xs max-w-52" placeholder="Search by reference…" /></div><Button variant="outline" size="sm">Search</Button></form></div>
        {!loading && data && <><div className="overflow-auto"><table><thead><tr><th>{screen === 'suppliers' ? 'Supplier' : 'Reference'}</th><th>{screen === 'suppliers' ? 'Email' : 'Supplier'}</th><th>{screen === 'suppliers' ? 'Phone' : 'Date'}</th>{screen !== 'suppliers' && <th>{screen === 'receipts' ? 'Line items' : 'Total excl. VAT'}</th>}<th className="!text-right">Actions</th></tr></thead><tbody>{data.items.map(row => <tr key={row.id} className="hover:bg-slate-50/60"><td><button className="font-semibold text-teal-800 hover:underline" onClick={() => setEditor({ record: row })}>{row.name || row.number}</button></td><td className="text-slate-500">{screen === 'suppliers' ? row.email || '—' : suppliers.find(s => s.id === row.supplier_id)?.name || '—'}</td><td className="text-slate-500">{screen === 'suppliers' ? row.phone || '—' : row.date}</td>{screen !== 'suppliers' && <td className="font-medium">{screen === 'receipts' ? `${row.lines?.length} lines` : money(row.total || '0.00', row.currency || 'SAR')}</td>}<td><div className="flex justify-end gap-1">{deleting === row.id ? <><span className="text-xs self-center mr-2">Delete?</span><Button variant="destructive" size="sm" disabled={busy} onClick={() => remove(row.id)}>Confirm</Button><Button variant="ghost" size="sm" onClick={() => setDeleting(null)}>Cancel</Button></> : <><Button variant="ghost" size="sm" onClick={() => setEditor({ record: row })} aria-label={`Edit ${row.name || row.number}`}><Pencil size={14} /></Button><Button variant="ghost" size="sm" onClick={() => setDeleting(row.id)} aria-label={`Delete ${row.name || row.number}`}><Trash2 size={14} /></Button></>}</div></td></tr>)}</tbody></table></div>{!data.items.length && <div className="text-center py-16"><ClipboardList className="mx-auto text-slate-300 mb-4" size={32} /><h3 className="font-semibold">{search ? 'No matching records' : 'Your ledger starts here'}</h3><p className="text-sm text-slate-500 mt-2">{search ? 'Try a different search.' : 'Use the New button to add your first record.'}</p></div>}<div className="flex items-center justify-between p-4 border-t border-slate-100 text-xs text-slate-400"><span>Page {page} of {Math.max(1, Math.ceil(data.total / 10))}</span><div className="flex gap-2"><Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page"><ChevronLeft size={14} /></Button><Button variant="outline" size="sm" disabled={page * 10 >= data.total} onClick={() => setPage(page + 1)} aria-label="Next page"><ChevronRight size={14} /></Button></div></div></>}
      </section>}
      {screen === 'members' && !loading && <section className="card p-6">{org.role === 'owner' && <form onSubmit={addMember} className="border-b border-slate-100 pb-6 mb-4"><h2 className="font-semibold mb-2">Add a colleague</h2><p className="text-xs text-slate-500 mb-4">They must register an account first. Members can manage procurement records.</p><div className="flex max-w-lg gap-3"><input name="email" type="email" aria-label="Colleague email" placeholder="colleague@company.com" required /><Button disabled={busy}>Add member</Button></div></form>}{members.map(member => <div key={member.id} className="flex items-center justify-between py-4 border-b last:border-0 border-slate-100"><div><p className="font-semibold">{member.name}<span className="ml-3 text-[10px] uppercase tracking-wide text-teal-700 bg-teal-50 px-2 py-1 rounded">{member.role}</span></p><p className="text-xs text-slate-500 mt-2">{member.email}</p></div>{org.role === 'owner' && member.role !== 'owner' && (deleting === member.id ? <div className="flex gap-2"><Button variant="destructive" size="sm" disabled={busy} onClick={() => remove(member.id)}>Confirm removal</Button><Button variant="ghost" size="sm" onClick={() => setDeleting(null)}>Cancel</Button></div> : <Button variant="outline" size="sm" onClick={() => setDeleting(member.id)}>Remove</Button>)}</div>)}</section>}
      <footer className="mt-10 text-[11px] text-slate-400 flex justify-between gap-4"><span>MatchLedger · Procurement workspace</span><span>Amounts exclude VAT</span></footer>
    </main>
    {editor && <RecordEditor key={`${auth.organization_id}-${screen}-${editor.record?.id || 'new'}`} resource={screen} record={editor.record} suppliers={suppliers} orders={orders} auth={auth} onClose={() => setEditor(null)} onSaved={() => { setEditor(null); setNotice('Record saved.'); setVersion(v => v + 1); }} />}
  </div>;
}


