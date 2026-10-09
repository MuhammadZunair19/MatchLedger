export type Auth = { user: { id: string; name: string; email: string }; csrf_token: string; organization_id: string; organizations: { id: string; name: string; role: string }[] };
export type Line = { id?: string; description: string; quantity: string; unit_price?: string; purchase_order_line_id?: string; amount?: string };
export type RecordRow = { id: string; name?: string; email?: string; phone?: string; address?: string; number?: string; date?: string; supplier_id?: string; purchase_order_id?: string; currency?: string; notes?: string; lines?: Line[]; total?: string; created_at: string };
export type Page = { items: RecordRow[]; total: number; page: number; page_size: number };
export async function api<T>(path: string, options: RequestInit = {}, csrf?: string): Promise<T> {
  const response = await fetch(`/api${path}`, { ...options, headers: { 'Content-Type': 'application/json', ...(csrf ? { 'X-CSRF-Token': csrf } : {}), ...options.headers } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const error = body.error;
    throw new Error(error?.details?.map((d: { field: string; message: string }) => `${d.field}: ${d.message}`).join('; ') || error?.message || `Request failed (${response.status})`);
  }
  return response.status === 204 ? undefined as T : response.json();
}
export function money(value: string, currency: string) {
  const [whole, fraction = '00'] = value.split('.');
  return `${currency} ${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${fraction.padEnd(2, '0')}`;
}
export async function allRecords(path: string) {
  const items: RecordRow[] = [];
  let page = 1;
  while (true) {
    const result = await api<Page>(`/${path}?page=${page}&page_size=100`);
    items.push(...result.items);
    if (items.length >= result.total || !result.items.length) return items;
    page++;
  }
}
