import Workspace from '@/components/workspace';

const rootScreens = new Set(['dashboard', 'suppliers', 'purchase-orders', 'receipts', 'invoices', 'members']);

export default async function Home({ searchParams }: { searchParams: Promise<{ screen?: string }> }) {
  const requested = (await searchParams).screen || 'dashboard';
  return <Workspace initialScreen={rootScreens.has(requested) ? requested : 'dashboard'} />;
}
