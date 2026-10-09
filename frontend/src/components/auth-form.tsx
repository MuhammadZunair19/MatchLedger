'use client';
import { useState } from 'react';
import { ArrowRight, Layers3 } from 'lucide-react';
import { api, Auth } from '@/lib/api';
import { Button } from './ui/button';
export default function AuthForm({ onAuth }: { onAuth: (auth: Auth) => void }) {
  const [register, setRegister] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('');
    const values = Object.fromEntries(new FormData(event.currentTarget));
    try { onAuth(await api<Auth>(`/auth/${register ? 'register' : 'login'}`, { method: 'POST', body: JSON.stringify(values) })); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <main className="min-h-screen grid lg:grid-cols-2">
    <section className="bg-[#122c3c] text-white p-10 lg:p-20 flex flex-col justify-between gap-16">
      <div className="flex items-center gap-3 text-2xl font-bold"><Layers3 className="text-teal-300" /> MatchLedger<span className="text-teal-300">.</span></div>
      <div><p className="eyebrow text-teal-300 mb-5">A clearer view of procurement</p><h1 className="text-4xl lg:text-6xl font-semibold leading-tight tracking-tight">Every order.<br />Every delivery.<br /><span className="text-teal-300">One connected ledger.</span></h1><p className="text-slate-300 mt-7 max-w-md text-base leading-7">Keep your suppliers, purchase orders, delivery receipts and invoices together in a workspace built for your team.</p></div>
      <p className="text-slate-400 text-xs">MatchLedger · Milestone 1 / Procurement records</p>
    </section>
    <section className="flex items-center justify-center p-8"><div className="w-full max-w-sm"><p className="eyebrow text-teal-700 mb-3">Your procurement workspace</p><h2 className="text-3xl font-semibold">{register ? 'Start your ledger' : 'Welcome back'}</h2><p className="text-slate-500 mt-3 mb-8">{register ? 'Create an account and your organization.' : 'Sign in to continue to your organization.'}</p>
      <form onSubmit={submit} className="space-y-5">
        {register && <><label>Full name<input name="name" required maxLength={120} autoComplete="name" /></label><label>Organization name<input name="organization_name" required maxLength={160} autoComplete="organization" /></label></>}
        <label>Email address<input type="email" name="email" required autoComplete="email" /></label>
        <label>Password<input type="password" name="password" required minLength={register ? 12 : 1} maxLength={128} autoComplete={register ? 'new-password' : 'current-password'} /></label>
        {register && <p className="text-xs text-slate-500">Use at least 12 characters.</p>}
        {error && <p role="alert" className="text-red-700 bg-red-50 rounded-lg p-3">{error}</p>}
        <Button disabled={busy} className="w-full">{busy ? 'Please wait…' : register ? 'Create workspace' : 'Sign in'}<ArrowRight size={16} /></Button>
      </form><p className="text-sm text-slate-500 mt-6">{register ? 'Already have an account?' : 'New to MatchLedger?'} <button className="text-teal-700 font-semibold" onClick={() => { setRegister(!register); setError(''); }}>{register ? 'Sign in' : 'Create workspace'}</button></p>
    </div></section>
  </main>;
}
