'use client';

import { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Archive,
  Bot,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  CreditCard,
  Database,
  Download,
  FileText,
  Gauge,
  Gift,
  Home,
  KeyRound,
  Layers3,
  LayoutDashboard,
  ListChecks,
  LogOut,
  Menu,
  Package,
  Plus,
  RefreshCw,
  Save,
  Search,
  Server,
  Settings,
  ShieldCheck,
  ShoppingCart,
  Tag,
  Trash2,
  Upload,
  UserCog,
  Users,
  Wallet,
  X,
  XCircle
} from 'lucide-react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from 'recharts';
import { fetchJson, getAction, submitForm } from '@/lib/api';

import { gbFromBytes, money, pct, shortDate, toman } from '@/lib/format';

function adminCsrfHeaders(): HeadersInit {
  const raw = typeof document === 'undefined' ? '' : (document.cookie.split('; ').find((x) => x.startsWith('dbot_csrf_token=')) || '');
  const csrf = raw ? decodeURIComponent(raw.split('=').slice(1).join('=')) : '';
  return { Accept: 'application/json', 'X-Requested-With': 'fetch', ...(csrf ? { 'X-CSRF-Token': csrf } : {}) };
}

type SectionKey =
  | 'dashboard'
  | 'service-types'
  | 'test-account'
  | 'openvpn-profiles'
  | 'plans'
  | 'payments'
  | 'orders-report'
  | 'discounts'
  | 'users'
  | 'resellers'
  | 'servers'
  | 'categories'
  | 'backup'
  | 'settings';

type DashboardApi = {
  ok: boolean;
  stats: Record<string, number>;
  resources: ResourceMetric[];
  chart_ranges: { range: number; data: { date: string; label: string; sales: number }[] }[];
  latest_orders: OrderItem[];
};

type ResourceMetric = { title: string; value: string; detail: string; percent: number; icon: string; cls: string };
type UserItem = { id: number; telegram_id: number; username?: string; full_name?: string; wallet_total: number; purchases: number; referral_code?: string; joined_at?: string; is_blocked?: boolean; is_reseller?: boolean };
type ServerItem = { id: number; name: string; display_name?: string; server_type: string; server_type_label?: string; panel_url: string; panel_base_url?: string; panel_path?: string; subscription_url?: string; username: string; auth_username?: string; scope?: string; inbound_ids?: unknown[]; inbounds?: { id: number; remark?: string; protocol?: string; enable?: boolean }[]; last_inbound_sync_at?: string; is_active: boolean; user_count?: number; router_name?: string; router_host?: string; router_port?: string | number; router_online?: boolean; router_identity?: string; router_version?: string; router_uptime?: string; router_secrets?: number; router_active?: number; router_error?: string; last_router_sync_at?: string; default_protocol?: string; openvpn_profile_id?: number; l2tp_server?: string; l2tp_ipsec_secret?: string; badge_color?: string; badge_emoji?: string; badge_label?: string };
type CategoryItem = { id: number; name: string; server_id?: number | null; server_ids?: number[]; server_names?: string[]; is_active?: boolean };
type PlanItem = { id: number; title: string; volume_gb: number; duration_days: number; price_irt: number; category_id?: number; server_id?: number; inbound_ids?: unknown[]; inbound_mode?: 'automatic' | 'manual'; is_active: boolean; is_unlimited?: boolean };
type ResellerPackage = { id: number; title: string; server_id?: number; volume_gb: number; price_irt: number; reseller_validity_days: number; is_active: boolean };
type PaymentItem = { id: number; server_type: string; server_id?: number; card_number: string; owner_name: string; is_active: boolean };
type DiscountItem = { id: number; code: string; discount_type: string; value: number; max_uses: number; per_user_limit: number; used_count: number; expires_at?: string; is_active: boolean; allowed_server_ids?: number[]; allowed_server_names?: string[] };
type ResellerItem = { id: number; user: UserItem; total_bytes: number; used_bytes: number; reserved_bytes: number; remaining_bytes?: number; expires_at?: string; is_active: boolean; created_at?: string };
type ResellerServiceItem = { id: number; username: string; panel_username?: string; server_id?: number | null; server_name?: string; server_type?: string; plan_title?: string; total_bytes: number; used_bytes: number; remaining_bytes: number; used_percent: number; expires_at?: string; created_at?: string; is_active: boolean; disabled_reason?: string };
type ResellerServicesApi = { ok: boolean; reseller: ResellerItem; items: ResellerServiceItem[]; total: number };
type OrderItem = { id: number; user?: UserItem | null; plan?: PlanItem | null; amount_irt: number; status: string; payment_method?: string; rejection_reason?: string | null; rejected_by?: number | null; rejected_at?: string | null; receipt_file_id?: string | null; created_at?: string };
type SettingItem = { key: string; value: string; is_active?: boolean };
type ServiceTypeItem = { key: string; value: string; is_active: boolean };
type BackupSettings = { ok: boolean; settings: Record<string, string>; status: { configured: boolean; last_test_status?: string; last_test_message?: string; last_backup_status?: string; last_backup_message?: string; last_backup_at?: string; admin_ok?: boolean } };
type BackupFormState = { destination: string; bot_token: string; chat_id: string; bot_username: string; time: string; include_database: string; include_files: string };
type BackupTestState = { status: 'idle' | 'ok' | 'bad'; message: string; adminOk?: boolean };
type TestAccountApi = { ok: boolean; settings: Record<string, string>; usage_count: number; usage_items?: { id: number; telegram_id: number; created_at?: string; service_id?: number | null; user?: UserItem | null }[]; servers: ServerItem[] };
type OpenVPNProfileItem = { id: number; name: string; server_id?: number | null; file_name: string; content: string; is_active: boolean; created_at?: string };
type OpenVPNProfilesApi = { ok: boolean; items: OpenVPNProfileItem[]; servers: ServerItem[] };


type ApiList<T> = { ok: boolean; items: T[]; total?: number; page?: number; page_size?: number };

function circleEmojiForColor(color?: string): string {
  const raw = String(color || '').trim().toLowerCase();
  const presets: Record<string, string> = {
    '#ef4444': '🔴', '#dc2626': '🔴', '#ff0000': '🔴',
    '#f97316': '🟠', '#ea580c': '🟠', '#ff7a00': '🟠',
    '#eab308': '🟡', '#facc15': '🟡', '#ffff00': '🟡',
    '#22c55e': '🟢', '#16a34a': '🟢', '#00ff00': '🟢',
    '#2563eb': '🔵', '#3b82f6': '🔵', '#0000ff': '🔵',
    '#7c3aed': '🟣', '#9333ea': '🟣', '#8000ff': '🟣',
    '#111827': '⚫', '#000000': '⚫',
    '#ffffff': '⚪', '#f8fafc': '⚪',
    '#92400e': '🟤', '#a16207': '🟤', '#8b4513': '🟤'
  };
  if (presets[raw]) return presets[raw];
  const match = raw.match(/^#([0-9a-f]{6})$/i);
  if (!match) return '🔵';
  const hex = match[1];
  const r = parseInt(hex.slice(0, 2), 16);
  const g = parseInt(hex.slice(2, 4), 16);
  const b = parseInt(hex.slice(4, 6), 16);
  if (Math.max(r, g, b) < 50) return '⚫';
  if (Math.min(r, g, b) > 220) return '⚪';
  if (r > 120 && g > 65 && b < 80) return r < 190 && g < 130 ? '🟤' : '🟠';
  if (r >= 190 && g >= 150 && b < 110) return '🟡';
  if (g >= r && g >= b) return '🟢';
  if (b >= r && b >= g) return r < 130 ? '🔵' : '🟣';
  if (r >= g && r >= b) return '🔴';
  return '🔵';
}

type PlansApi = { ok: boolean; plans: PlanItem[]; reseller_packages: ResellerPackage[] };

type ModalForm = {
  title: string;
  action: string;
  fields: FieldConfig[];
  defaults?: Record<string, any>;
};

type FieldConfig = {
  name: string;
  label: string;
  type?: 'text' | 'number' | 'password' | 'select' | 'multiselect' | 'checkbox-group' | 'textarea' | 'time' | 'date' | 'user-search' | 'file' | 'color';
  required?: boolean;
  full?: boolean;
  options?: { value: string | number; label: string }[];
  optionsBy?: { name: string; map: Record<string, { value: string | number; label: string }[]> };
  placeholder?: string;
  showWhen?: { name: string; value?: string; values?: string[] };
  showWhenAll?: { name: string; value?: string; values?: string[] }[];
  hidden?: boolean;
};

const navGroups: { label: string; items: { key: SectionKey; title: string; href: string; icon: any }[] }[] = [
  { label: 'Main', items: [{ key: 'dashboard', title: 'Dashboard', href: '/admin', icon: LayoutDashboard }] },
  {
    label: 'Sales',
    items: [
      { key: 'service-types', title: 'Service Types', href: '/admin/service-types', icon: Gift },
      { key: 'test-account', title: 'Test Account', href: '/admin/test-account', icon: ShieldCheck },
      { key: 'openvpn-profiles', title: 'Profile OpenVPN', href: '/admin/openvpn-profiles', icon: FileText },
      { key: 'plans', title: 'Plans', href: '/admin/plans', icon: Package },
      { key: 'payments', title: 'Payments', href: '/admin/payments', icon: CreditCard },
      { key: 'orders-report', title: 'Orders Report', href: '/admin/orders-report', icon: FileText },
      { key: 'discounts', title: 'Discount Codes', href: '/admin/discounts', icon: Tag }
    ]
  },
  { label: 'Users', items: [{ key: 'users', title: 'Users', href: '/admin/users', icon: Users }, { key: 'resellers', title: 'Resellers', href: '/admin/resellers', icon: UserCog }] },
  { label: 'System', items: [{ key: 'servers', title: 'Servers', href: '/admin/servers', icon: Server }, { key: 'categories', title: 'Categories', href: '/admin/categories', icon: Layers3 }, { key: 'backup', title: 'Backup & Restore', href: '/admin/backup', icon: Archive }, { key: 'settings', title: 'Settings', href: '/admin/settings', icon: Settings }] }
];

const sectionTitles: Record<SectionKey, { title: string; subtitle: string }> = {
  dashboard: { title: 'Dashboard 👋', subtitle: '' },
  'service-types': { title: 'Service Types', subtitle: 'Create and manage the service categories visible inside the bot.' },
  'test-account': { title: 'Test Account', subtitle: 'Configure the trial account users can receive from the Telegram bot.' },
  'openvpn-profiles': { title: 'Profile OpenVPN', subtitle: 'Upload, edit, view and bind .ovpn server profiles for MikroTik / Custom plans.' },
  plans: { title: 'Plans', subtitle: 'Public plans and reseller packages with real server bindings.' },
  payments: { title: 'Payments', subtitle: 'Card-to-card and account destinations for public and reseller payments.' },
  'orders-report': { title: 'Orders Report', subtitle: 'Filter, review, and export all recent orders.' },
  discounts: { title: 'Discount Codes', subtitle: 'Percentage and fixed Toman discount codes with per-user limits.' },
  users: { title: 'Users', subtitle: 'Search all Telegram users, wallets, reseller access, referrals and purchases.' },
  resellers: { title: 'Resellers', subtitle: 'Manage reseller capacity, used traffic, and expiry dates.' },
  servers: { title: 'Servers', subtitle: 'Sanaei / 3x-ui servers and dedicated MikroTik / Custom router connections.' },
  categories: { title: 'Categories', subtitle: 'Group servers and plans for a clean purchase flow.' },
  backup: { title: 'Backup & Restore', subtitle: 'Configure website and bot backups, test Telegram delivery, and restore local backup files safely.' },
  settings: { title: 'Settings', subtitle: 'Bot texts, bot status, database info, website login and protected configuration values.' }
};

function statusClass(status?: string) {
  const s = String(status || '').toLowerCase();
  if (['paid', 'approved', 'completed', 'active', 'success'].some((x) => s.includes(x))) return 'green';
  if (['pending', 'waiting'].some((x) => s.includes(x))) return 'yellow';
  if (['failed', 'rejected', 'deleted', 'inactive', 'blocked'].some((x) => s.includes(x))) return 'red';
  return 'purple';
}

function firstLetter(value?: string | number | null) {
  return String(value || 'A').trim().charAt(0).toUpperCase() || 'A';
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function daysAgoIso(days: number) {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

function orderUserName(order: OrderItem) {
  return order.user?.full_name || order.user?.username || order.user?.telegram_id || 'User';
}

function orderPlanTitle(order: OrderItem) {
  const pm = String(order.payment_method || '').toLowerCase();
  if (order.plan?.title) return order.plan.title;
  if (pm.includes('wallet') || pm.includes('charge') || pm.includes('topup')) return 'Wallet';
  if (pm.includes('reseller')) return 'Reseller Order';
  return 'Custom Order';
}

function paymentLabel(value?: string | null) {
  const pm = String(value || '').toLowerCase();
  if (!pm || pm === '-') return '-';
  if (pm.includes('wallet') || pm.includes('balance')) return 'Wallet';
  if (pm.includes('card') || pm.includes('cart') || pm.includes('receipt') || pm.includes('manual') || pm.includes('bank')) return 'Card to Card';
  if (pm.includes('crypto') || pm.includes('nowpayments') || pm.includes('trx')) return 'Crypto';
  if (pm.includes('reseller')) return 'Reseller Payment';
  return value || '-';
}

function tomanChart(value: number) {
  return Math.round(Number(value || 0) / 1000).toLocaleString('en-US');
}

function useToast() {
  const [toast, setToast] = useState<{ text: string; good: boolean } | null>(null);
  const show = (text: string, good = true) => {
    setToast({ text, good });
    window.setTimeout(() => setToast(null), 2800);
  };
  return { toast, show };
}

export function AdminDashboard({ initialSection }: { initialSection: SectionKey }) {
  const [section, setSection] = useState<SectionKey>(initialSection);
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [globalQuery, setGlobalQuery] = useState('');
  const [modal, setModal] = useState<ModalForm | null>(null);
  const [profileOpen, setProfileOpen] = useState(false);
  const [profileAvatar, setProfileAvatar] = useState<string>('');
  const [reloadKey, setReloadKey] = useState(0);
  const [authRequired, setAuthRequired] = useState(false);
  const [dateRange, setDateRange] = useState({ start: daysAgoIso(30), end: todayIso() });
  const { toast, show } = useToast();

  useEffect(() => setSection(initialSection), [initialSection]);
  useEffect(() => {
    setProfileAvatar(localStorage.getItem('dbot_admin_avatar') || '');
  }, []);

  useEffect(() => {
    if (!mobileOpen) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMobileOpen(false);
    };
    const onResize = () => {
      if (window.innerWidth > 860) setMobileOpen(false);
    };

    document.body.classList.add('sidebar-open');
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('resize', onResize);
    return () => {
      document.body.classList.remove('sidebar-open');
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('resize', onResize);
    };
  }, [mobileOpen]);

  const title = sectionTitles[section];

  function openSection(item: { key: SectionKey; href: string }, event?: any) {
    event?.preventDefault();
    setSection(item.key);
    setMobileOpen(false);
    if (typeof window !== 'undefined' && window.location.pathname !== item.href) {
      window.history.pushState({}, '', item.href);
    }
  }

  useEffect(() => {
    const onPop = () => {
      const match = navGroups.flatMap((g) => g.items).find((x) => x.href === window.location.pathname);
      if (match) setSection(match.key);
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  async function submitModal(values: Record<string, FormDataEntryValue>) {
    if (!modal) return;
    try {
      const result: any = await submitForm(modal.action, values.badge_color ? { ...values, badge_emoji: circleEmojiForColor(String(values.badge_color)) } : values);
      if (result?.logout || modal.action === '/admin/settings/website' && (String(values.username || '').trim() || String(values.password || '').trim())) {
        show(result?.message || 'Website login changed. Please login again.', true);
        window.setTimeout(() => { window.location.href = result?.redirect || '/login?updated=1'; }, 650);
        return;
      }
      show('Saved successfully', true);
      setModal(null);
      setReloadKey((x) => x + 1);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg === 'AUTH_REQUIRED') setAuthRequired(true);
      show(msg === 'AUTH_REQUIRED' ? 'Please login again' : msg, false);
    }
  }

  async function runAction(path: string, message = 'Action completed') {
    if (!window.confirm('Are you sure?')) return;
    try {
      await getAction(path);
      show(message, true);
      setReloadKey((x) => x + 1);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg === 'AUTH_REQUIRED') setAuthRequired(true);
      show(msg === 'AUTH_REQUIRED' ? 'Please login again' : msg, false);
    }
  }

  if (authRequired) {
    return (
      <main className="login-state">
        <section className="card login-card">
          <div className="logo-mark mx-auto mb-4"><span>D</span></div>
          <h1>Login required</h1>
          <p className="muted">Your admin session is not active. Login again to open the D BOT admin panel.</p>
          <a className="btn primary mt-4" href="/login">Open Login</a>
        </section>
        {toast && <div className={`toast ${toast.good ? 'good' : 'bad'}`}>{toast.text}</div>}
      </main>
    );
  }

  return (
    <div className="shell">
      <aside className={`sidebar ${collapsed ? 'collapsed' : ''} ${mobileOpen ? 'mobile-open' : ''}`}>
        <div className="sidebar-head">
          <a className="brand" href="/admin" onClick={(event) => openSection({ key: 'dashboard', href: '/admin' }, event)}>
            <div className="logo-mark"><span>D</span></div>
            <div className="brand-copy"><strong>D BOT</strong></div>
          </a>
          <button className="sidebar-close" type="button" aria-label="Close sidebar" onClick={() => setMobileOpen(false)}>
            <X size={21} />
          </button>
        </div>
        <nav className="sidebar-nav" aria-label="Admin navigation">
          {navGroups.map((group) => (
            <div className="nav-section" key={group.label}>
              <div className="nav-section-title">{group.label}</div>
              {group.items.map((item) => {
                const Icon = item.icon;
                return (
                  <a key={item.key} className={`nav-link ${section === item.key ? 'active' : ''}`} href={item.href} onClick={(event) => openSection(item, event)}>
                    <Icon /> <span className="nav-title">{item.title}</span>
                  </a>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="sidebar-footer">
          <button className="collapse-btn" onClick={() => setCollapsed((x) => !x)}><ChevronLeft size={18} /><span>Collapse</span></button>
        </div>
      </aside>
      <button
        type="button"
        className={`sidebar-backdrop ${mobileOpen ? 'visible' : ''}`}
        aria-label="Close navigation"
        tabIndex={mobileOpen ? 0 : -1}
        onClick={() => setMobileOpen(false)}
      />

      <main className="main">
        <header className="topbar">
          <div className="top-left">
            <button className="menu-btn" type="button" aria-label="Open navigation" aria-expanded={mobileOpen} onClick={() => setMobileOpen((x) => !x)}><Menu /></button>
            <label className="searchbox"><Search size={18} /><input value={globalQuery} onChange={(e) => setGlobalQuery(e.target.value)} placeholder="Search anything..." /><span className="kbd">⌘ K</span></label>
          </div>
          <div className="top-actions only-profile">
            <button className="profile profile-button" onClick={() => setProfileOpen(true)}>
              <div className="avatar">{profileAvatar ? <img src={profileAvatar} alt="Admin" /> : 'A'}</div>
              <div className="profile-copy"><b>Admin</b><small>Owner</small></div><ChevronDown size={16} />
            </button>
          </div>
        </header>

        <div className="content">
          <div className="page-title">
            <div><h1>{title.title}</h1>{title.subtitle ? <p>{title.subtitle}</p> : null}</div>
            <div className="actions">
              {section === 'dashboard' && <DateRangePicker value={dateRange} onChange={setDateRange} onApply={() => setReloadKey((x) => x + 1)} />}
              {section === 'orders-report' && <a href="/admin/orders-report/pdf?all=1" className="btn"><Download size={16} /> Export PDF</a>}
              {section !== 'dashboard' && <button className="btn" onClick={() => setReloadKey((x) => x + 1)}><RefreshCw size={16} /> Refresh</button>}
            </div>
          </div>

          <SectionRenderer section={section} query={globalQuery} reloadKey={reloadKey} dateRange={dateRange} setAuthRequired={setAuthRequired} openModal={setModal} runAction={runAction} show={show} />
        </div>
      </main>
      {modal && <FormModal modal={modal} onClose={() => setModal(null)} onSubmit={submitModal} show={show} />}
      {profileOpen && <ProfileModal avatar={profileAvatar} setAvatar={setProfileAvatar} onClose={() => setProfileOpen(false)} show={show} />}
      {toast && <div className={`toast ${toast.good ? 'good' : 'bad'}`}>{toast.text}</div>}
    </div>
  );
}

function DateRangePicker({ value, onChange, onApply }: { value: { start: string; end: string }; onChange: (v: { start: string; end: string }) => void; onApply: () => void }) {
  return (
    <div className="date-filter">
      <CalendarDays size={17} />
      <input type="date" value={value.start} onChange={(e) => onChange({ ...value, start: e.target.value })} />
      <span>to</span>
      <input type="date" value={value.end} onChange={(e) => onChange({ ...value, end: e.target.value })} />
      <button className="btn primary mini" onClick={onApply}>Apply</button>
    </div>
  );
}

function ProfileModal({ avatar, setAvatar, onClose, show }: { avatar: string; setAvatar: (v: string) => void; onClose: () => void; show: (m: string, good?: boolean) => void }) {
  function upload(file?: File | null) {
    if (!file) return;
    if (!file.type.startsWith('image/')) { show('Please choose an image file', false); return; }
    const reader = new FileReader();
    reader.onload = () => {
      const data = String(reader.result || '');
      localStorage.setItem('dbot_admin_avatar', data);
      setAvatar(data);
      show('Profile photo updated', true);
    };
    reader.readAsDataURL(file);
  }
  return (
    <div className="modal-backdrop">
      <motion.div className="modal-card profile-modal" initial={{ scale: .96, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}>
        <div className="modal-head"><h2>Admin Profile</h2><button className="icon-btn" onClick={onClose}><X size={18} /></button></div>
        <div className="profile-preview avatar">{avatar ? <img src={avatar} alt="Admin" /> : 'A'}</div>
        <p className="muted">Role: <b>Owner</b></p>
        <label className="btn primary file-btn"><Upload size={16} /> Upload profile image<input type="file" accept="image/*" onChange={(e) => upload(e.target.files?.[0])} /></label>
        <button className="btn" onClick={() => { localStorage.removeItem('dbot_admin_avatar'); setAvatar(''); show('Profile photo removed', true); }}>Remove photo</button>
        <a className="btn danger" href="/logout"><LogOut size={16} /> Logout</a>
      </motion.div>
    </div>
  );
}

function SectionRenderer(props: { section: SectionKey; query: string; reloadKey: number; dateRange: { start: string; end: string }; setAuthRequired: (v: boolean) => void; openModal: (form: ModalForm) => void; runAction: (path: string, message?: string) => void; show: (message: string, good?: boolean) => void }) {
  switch (props.section) {
    case 'dashboard': return <DashboardSection {...props} />;
    case 'users': return <UsersSection {...props} />;
    case 'servers': return <ServersSection {...props} />;
    case 'categories': return <CategoriesSection {...props} />;
    case 'plans': return <PlansSection {...props} />;
    case 'payments': return <PaymentsSection {...props} />;
    case 'discounts': return <DiscountsSection {...props} />;
    case 'resellers': return <ResellersSection {...props} />;
    case 'orders-report': return <OrdersSection {...props} />;
    case 'settings': return <SettingsSection {...props} />;
    case 'backup': return <BackupSection {...props} />;
    case 'service-types': return <ServiceTypesSection {...props} />;
    case 'test-account': return <TestAccountSection {...props} />;
    case 'openvpn-profiles': return <OpenVPNProfilesSection {...props} />;
    default: return null;
  }
}

function useApi<T>(path: string, reloadKey: number, setAuthRequired: (v: boolean) => void) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError('');
    fetchJson<T>(path)
      .then((json) => { if (!cancelled) setData(json); })
      .catch((err) => {
        const msg = err instanceof Error ? err.message : String(err);
        if (msg === 'AUTH_REQUIRED') setAuthRequired(true);
        if (!cancelled) setError(msg);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [path, reloadKey, setAuthRequired]);
  return { data, loading, error, setData };
}

function DashboardSection({ reloadKey, setAuthRequired, dateRange, show }: any) {
  const qs = `start_date=${encodeURIComponent(dateRange.start)}&end_date=${encodeURIComponent(dateRange.end)}`;
  const { data, loading, error } = useApi<DashboardApi>(`/admin/api/v2/dashboard?${qs}`, reloadKey, setAuthRequired);
  const chartData = data?.chart_ranges?.[0]?.data || [];
  const stats = data?.stats || {};
  if (loading) return <SkeletonGrid />;
  if (error || !data) return <EmptyState message={error || 'Dashboard could not be loaded.'} />;
  const statCards = [
    { label: 'Total Revenue', value: toman(stats.monthly_sales), trend: stats.monthly_sales_change, icon: Gauge, cls: 'purple' },
    { label: 'New Orders', value: money(stats.today_orders), trend: stats.orders_change, icon: ShoppingCart, cls: 'blue' },
    { label: 'Total Users', value: money(stats.users_total), trend: stats.users_change, icon: Users, cls: 'green' },
    { label: 'Active Services', value: money(stats.active_services), trend: stats.conversion_rate, icon: Server, cls: 'cyan' }
  ];
  return (
    <>
      <div className="cards4">
        {statCards.map((card, index) => <StatCard key={card.label} {...card} index={index} />)}
      </div>
      <div className="dashboard-grid">
        <section className="panel">
          <div className="panel-head">
            <h2>Revenue Overview</h2>
            <div className="actions"><a className="btn" href="/admin/orders-report/pdf?all=1"><Download size={15} /> Export</a><a className="btn primary" href={`/admin/orders-report?start_date=${dateRange.start}&end_date=${dateRange.end}`}>View Report</a></div>
          </div>
          <div className="panel-title-value"><strong>{toman(stats.monthly_sales)}</strong><span className="stat-trend">{pct(stats.monthly_sales_change)} vs previous range</span></div>
          <div className="chart-wrap">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
                <defs><linearGradient id="rev" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#7c3aed" stopOpacity={0.65}/><stop offset="95%" stopColor="#7c3aed" stopOpacity={0}/></linearGradient></defs>
                <CartesianGrid stroke="rgba(148,163,184,.12)" vertical={false} />
                <XAxis dataKey="label" tick={{ fill: '#aab4c8', fontSize: 12 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: '#aab4c8', fontSize: 12 }} axisLine={false} tickLine={false} tickFormatter={(v) => tomanChart(Number(v))} />
                <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid rgba(148,163,184,.2)', borderRadius: 12 }} formatter={(value) => `${tomanChart(Number(value))} × 1,000 Toman`} />
                <Area type="monotone" dataKey="sales" stroke="#8b5cf6" strokeWidth={3} fill="url(#rev)" dot={false} activeDot={{ r: 7 }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </section>
        <div className="side-stack">
          <SystemStatus resources={data.resources} />
          <RecentActivities orders={data.latest_orders} />
        </div>
      </div>
      <RecentOrders orders={data.latest_orders} />
    </>
  );
}

function StatCard({ label, value, trend, icon: Icon, cls, index }: any) {
  return (
    <motion.div className={`card stat-card ${cls}`} initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * .06 }} tabIndex={0}>
      <div className="stat-head"><div><div className="stat-label">{label}</div><div className="stat-value">{value}</div><div className="stat-trend">{pct(trend)} <span className="muted">vs previous range</span></div></div><div className="stat-icon"><Icon size={22} /></div></div>
    </motion.div>
  );
}

function SystemStatus({ resources }: { resources: ResourceMetric[] }) {
  const fallback = [{ title: 'CPU Usage', percent: 32, cls: 'blue', icon: '⚙️', value: '32%', detail: 'Live' }, { title: 'RAM Usage', percent: 45, cls: 'purple', icon: '🧠', value: '45%', detail: 'Live' }, { title: 'Disk Usage', percent: 67, cls: 'yellow', icon: '💾', value: '67%', detail: 'Live' }, { title: 'Network', percent: 23, cls: 'green', icon: '↗', value: '23%', detail: 'Live' }];
  const rows = resources?.length ? resources : fallback;
  return <section className="panel"><div className="panel-head"><h2>System Status</h2></div><div className="progress-list">{rows.map((r) => <div className={`progress-row ${r.cls}`} key={r.title}><div className="progress-name"><span className="progress-icon">{r.icon}</span>{r.title.replace('Ram', 'RAM Usage').replace('SSD', 'Disk Usage').replace('CPU', 'CPU Usage')}</div><div className="progress-track"><div className="progress-fill" style={{ width: `${Math.min(100, Math.max(0, Number(r.percent || 0)))}%` }} /></div><b>{Math.round(Number(r.percent || 0))}%</b></div>)}</div></section>;
}

function RecentActivities({ orders }: { orders: OrderItem[] }) {
  const rows = orders.slice(0, 6);
  return <section className="panel"><div className="panel-head"><h2>Recent Activities</h2></div><div className="item-list">{rows.length ? rows.map((o) => <div className="list-row" key={o.id}><div className="row-left"><ShoppingCart size={16} /><div><b>{String(orderUserName(o))}</b> purchased <span className="text-sky-300">{orderPlanTitle(o)}</span></div></div><span className="muted">{shortDate(o.created_at)}</span></div>) : <EmptyInline />}</div></section>;
}

function RecentOrders({ orders }: { orders: OrderItem[] }) {
  return <section className="card table-card"><div className="panel-head"><h2>Recent Orders</h2><a className="btn" href="/admin/orders-report">View all</a></div><div className="table-scroll"><table><thead><tr><th>Order ID</th><th>User</th><th>Plan</th><th>Amount</th><th>Payment</th><th>Status</th><th>Date</th></tr></thead><tbody>{orders.map((o) => <tr key={o.id}><td className="text-violet-300">#ORD-{o.id}</td><td><div className="row-left"><span className="tiny-avatar">{firstLetter(o.user?.full_name || o.user?.username)}</span>{o.user?.full_name || o.user?.username || o.user?.telegram_id || '-'}</div></td><td>{orderPlanTitle(o)}</td><td>{toman(o.amount_irt)}</td><td>{paymentLabel(o.payment_method)}</td><td><span className={`badge ${statusClass(o.status)}`}>{o.status}</span></td><td>{shortDate(o.created_at)}</td></tr>)}</tbody></table></div></section>;
}

function UsersSection({ query, reloadKey, setAuthRequired }: any) {
  const [page, setPage] = useState(1);
  const pageSize = 100;
  useEffect(() => { setPage(1); }, [query]);
  const q = encodeURIComponent(query || '');
  const { data, loading, error } = useApi<ApiList<UserItem>>(`/admin/api/v2/users?page=${page}&page_size=${pageSize}&q=${q}`, reloadKey, setAuthRequired);
  if (loading) return <SkeletonGrid />;
  if (error || !data) return <EmptyState message={error || 'Users could not be loaded.'} />;
  const total = Number(data.total || data.items.length || 0);
  const totalPages = Math.max(1, Math.ceil(total / Number(data.page_size || pageSize)));
  const table = <DataTable title={`Users (${money(total)})`} columns={['User', 'Telegram ID', 'Reseller', 'Referral', 'Purchases', 'Wallet', 'Status', 'Joined']} rows={data.items.map((u) => [<div className="row-left" key="u"><span className="tiny-avatar">{firstLetter(u.full_name || u.username)}</span><div><b>{u.full_name || u.username || 'Unknown'}</b><div className="muted">@{u.username || '-'}</div></div></div>, u.telegram_id, <span key="r" className={`status-icon ${u.is_reseller ? 'ok' : 'no'}`}>{u.is_reseller ? <CheckCircle2 size={18} /> : <XCircle size={18} />}</span>, u.referral_code || '-', u.purchases, toman(u.wallet_total), <span key="s" className={`badge ${u.is_blocked ? 'red' : 'green'}`}>{u.is_blocked ? 'Blocked' : 'Active'}</span>, shortDate(u.joined_at)] )} />;
  return <>{table}{totalPages > 1 && <div className="pagination-card"><button className="btn" disabled={page <= 1} onClick={() => setPage((x) => Math.max(1, x - 1))}>Previous</button><span className="badge">Page {page} / {totalPages}</span><button className="btn primary" disabled={page >= totalPages} onClick={() => setPage((x) => Math.min(totalPages, x + 1))}>Next</button></div>}</>;
}


function OpenVPNProfilesSection({ reloadKey, setAuthRequired, query, openModal, runAction }: any) {
  const { data, loading, error } = useApi<OpenVPNProfilesApi>('/admin/api/v2/openvpn-profiles', reloadKey, setAuthRequired);
  if (loading) return <SkeletonGrid />;
  if (error || !data) return <EmptyState message={error || 'OpenVPN profiles could not be loaded.'} />;
  const rows = filterItems(data.items, query, ['name', 'file_name', 'content']);
  const serverOpts = serverOptions(data.servers || []);
  return <>
    <div className="filterbar"><button className="btn primary" onClick={() => openModal(openvpnProfileForm(serverOpts))}><Plus size={16} /> Add Profile</button><span className="badge">{rows.length} profiles</span></div>
    <div className="section-grid">{rows.map((p) => <EntityCard key={p.id} title={p.name} icon={<FileText />} badge={p.is_active ? 'Active' : 'Inactive'} badgeClass={p.is_active ? 'green' : 'red'} kvs={[["File", p.file_name], ['Server ID', p.server_id || '-'], ['Profile ID', p.id], ['Content size', `${p.content?.length || 0} chars`]]} actions={<><button className="btn" onClick={() => openModal(openvpnProfileForm(serverOpts, p))}>Edit / View text</button><button className={p.is_active ? 'btn danger' : 'btn success'} onClick={() => runAction(`/admin/toggle/openvpn-profiles/${p.id}`, p.is_active ? 'Profile deactivated' : 'Profile activated')}>{p.is_active ? 'Deactivate' : 'Activate'}</button><button className="btn danger" onClick={() => runAction(`/admin/openvpn-profiles/${p.id}/delete`, 'Profile deleted')}><Trash2 size={15} /> Delete</button></>} />)}</div>
  </>;
}

function ServersSection({ query, reloadKey, setAuthRequired, openModal, runAction, show }: any) {
  const api = useApi<ApiList<ServerItem>>('/admin/api/v2/servers', reloadKey, setAuthRequired);
  const [items, setItems] = useState<ServerItem[]>([]);
  const [refreshingId, setRefreshingId] = useState<number | null>(null);
  useEffect(() => { if (api.data?.items) setItems(api.data.items); }, [api.data]);
  const rows = filterItems(items, query, ['name', 'display_name', 'panel_url', 'username', 'router_name']);
  async function refreshOne(id: number) {
    if (!window.confirm('Test connection and update server status?')) return;
    setRefreshingId(id);
    try {
      const result: any = await getAction(`/admin/servers/${id}/refresh`);
      const fresh = await fetchJson<ApiList<ServerItem>>('/admin/api/v2/servers');
      setItems((prev) => prev.map((item) => fresh.items.find((x) => x.id === item.id) || item));
      show(result?.message || 'Connection OK. Server updated.', true);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg === 'AUTH_REQUIRED') setAuthRequired(true);
      show(msg === 'AUTH_REQUIRED' ? 'Please login again' : msg, false);
    } finally {
      setRefreshingId(null);
    }
  }
  if (api.loading) return <SkeletonGrid />;
  if (api.error || !api.data) return <EmptyState message={api.error || 'Servers could not be loaded.'} />;
  return <>
    <div className="filterbar">
      <button className="btn primary" onClick={() => openModal(serverForm())}><Plus size={16} /> Add Server</button>
      <span className="badge">{rows.length} servers</span>
    </div>
    <div className="section-grid">{rows.map((s) => {
      const isCustom = s.server_type === 'mikrotik';
      const serviceBadgeEmoji = s.badge_emoji || (isCustom ? '🟠' : '🔵');
      const serviceBadgeLabel = s.badge_label || (isCustom ? 'MikroTik / OpenVPN' : 'V2Ray');
      const serviceBadgeColor = s.badge_color || (isCustom ? '#f97316' : '#2563eb');
      const kvs: [string, any][] = isCustom ? [
        ['Service badge', `${serviceBadgeEmoji} ${serviceBadgeLabel}`],
        ['Circle color', serviceBadgeColor],
        ['Panel', 'MikroTik / Custom'],
        ['Router', s.router_name || s.username || '-'],
        ['Router host', s.router_host || '-'],
        ['Router port', s.router_port || '-'],
        ['PPP users', s.router_secrets || 0],
        ['Active', s.router_active || 0],
        ['Version', s.router_version || '-'],
        ['Last sync', s.last_router_sync_at || '-'],
        ['Scope', s.scope || 'all'],
        ['Login user', s.auth_username || '-'],
        ['URL', s.panel_url]
      ] : [
        ['Service badge', `${serviceBadgeEmoji} ${serviceBadgeLabel}`],
        ['Circle color', serviceBadgeColor],
        ['Panel', s.server_type_label || s.server_type],
        ['Users', s.user_count || 0],
        ['Inbounds', s.inbound_ids?.length || 0],
        ['Last sync', s.last_inbound_sync_at || '-'],
        ['Scope', s.scope || 'public'],
        ['Username', s.username],
        ['URL', s.panel_url],
        ['Path', s.panel_path || '-']
      ];
      const statusBadge = !s.is_active ? 'Inactive' : (isCustom ? (s.router_online === false ? 'Offline' : 'Online') : 'Active');
      const statusClassName = !s.is_active ? 'red' : (statusBadge === 'Online' || statusBadge === 'Active' ? 'green' : 'red');
      return <EntityCard key={s.id} title={`${serviceBadgeEmoji} ${s.display_name || s.name}`} icon={<Server />} badge={statusBadge} badgeClass={statusClassName} kvs={kvs} actions={<>
        <button className="btn success" disabled={refreshingId === s.id} onClick={() => refreshOne(s.id)}><RefreshCw size={15} className={refreshingId === s.id ? 'spin' : ''} /> {refreshingId === s.id ? 'Testing' : 'Test & Update'}</button>
        <button className="btn" onClick={() => openModal(serverForm(s))}>Edit</button>
        <button className={(s.is_active ? 'btn danger' : 'btn success')} onClick={() => runAction(`/admin/toggle/servers/${s.id}`, s.is_active ? 'Server deactivated' : 'Server activated')}>{s.is_active ? 'Deactivate' : 'Activate'}</button>
        <button className="btn" onClick={() => getAction(`/admin/servers/${s.id}/duplicate`).then(() => show('Server duplicated', true)).catch((e) => show(String(e), false))}>Duplicate</button>
        <button className="btn danger" onClick={() => getAction(`/admin/servers/${s.id}/delete`).then(() => setItems((prev) => prev.filter((x) => x.id !== s.id))).catch((e) => show(String(e), false))}><Trash2 size={15} /> Delete</button>
      </>} />;
    })}</div>
  </>;
}

function CategoriesSection({ query, reloadKey, setAuthRequired, openModal, runAction, show }: any) {
  const cats = useApi<ApiList<CategoryItem>>('/admin/api/v2/categories', reloadKey, setAuthRequired);
  const srvs = useApi<ApiList<ServerItem>>('/admin/api/v2/servers', reloadKey, setAuthRequired);
  const [categoryOrder, setCategoryOrder] = useState<CategoryItem[]>([]);
  const [draggingId, setDraggingId] = useState<number | null>(null);
  const [savingOrder, setSavingOrder] = useState(false);

  useEffect(() => {
    setCategoryOrder(cats.data?.items || []);
  }, [cats.data]);

  if (cats.loading || srvs.loading) return <SkeletonGrid />;
  if (cats.error || !cats.data) return <EmptyState message={cats.error || 'Categories could not be loaded.'} />;
  const options = serverOptions(srvs.data?.items || []);
  const rows = filterItems(categoryOrder, query, ['name']);
  const canReorder = !String(query || '').trim();

  function reorderCategories(list: CategoryItem[], fromId: number, toId: number) {
    const next = [...list];
    const from = next.findIndex((x) => x.id === fromId);
    const to = next.findIndex((x) => x.id === toId);
    if (from < 0 || to < 0 || from === to) return next;
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    return next;
  }

  async function saveCategoryOrder(list: CategoryItem[]) {
    setSavingOrder(true);
    try {
      await submitForm('/admin/categories/reorder', { ids: list.map((x) => x.id).join(',') });
      show('Category order saved for the Telegram bot', true);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg === 'AUTH_REQUIRED') setAuthRequired(true);
      show(msg === 'AUTH_REQUIRED' ? 'Please login again' : msg, false);
    } finally {
      setSavingOrder(false);
    }
  }

  function onDropCategory(targetId: number) {
    if (!canReorder || draggingId === null) return;
    const next = reorderCategories(categoryOrder, draggingId, targetId);
    setCategoryOrder(next);
    setDraggingId(null);
    saveCategoryOrder(next);
  }

  return <>
    <div className="filterbar"><button className="btn primary" onClick={() => openModal(categoryForm(options))}><Plus size={16} /> Add Category</button><span className="badge">{rows.length} categories</span></div>
    <div className="plan-order-note"><ListChecks size={16} /> Drag and drop category cards to set their top-to-bottom order inside the Telegram bot. {!canReorder && <b>Clear search to reorder.</b>} {savingOrder && <b>Saving...</b>}</div>
    <div className="section-grid plan-sort-grid">{rows.map((c) => {
      const linkedNames = c.server_names?.length ? c.server_names.join(', ') : (c.server_id ? `Server #${c.server_id}` : '-');
      const serverCount = c.server_ids?.length || (c.server_id ? 1 : 0);
      return <div key={c.id} className={`drag-card ${draggingId === c.id ? 'dragging' : ''}`} draggable={canReorder} onDragStart={() => canReorder && setDraggingId(c.id)} onDragOver={(e) => { if (canReorder) e.preventDefault(); }} onDrop={() => onDropCategory(c.id)} onDragEnd={() => setDraggingId(null)}><EntityCard title={c.name} icon={<Layers3 />} badge={c.is_active === false ? 'Inactive' : `${serverCount} server${serverCount === 1 ? '' : 's'}`} badgeClass={c.is_active === false ? 'red' : 'purple'} kvs={[['Category ID', c.id], ['Linked servers', linkedNames], ['Server IDs', c.server_ids?.join(', ') || c.server_id || '-']]} actions={<><span className="drag-handle"><ListChecks size={15} /> Drag</span><button className="btn" onClick={() => openModal(categoryForm(options, c))}>Edit</button><button className={c.is_active === false ? 'btn success' : 'btn danger'} onClick={() => runAction(`/admin/toggle/categories/${c.id}`, c.is_active === false ? 'Category activated' : 'Category deactivated')}>{c.is_active === false ? 'Activate' : 'Deactivate'}</button><button className="btn danger" onClick={() => runAction(`/admin/categories/${c.id}/delete`, 'Category deleted')}>Delete</button></>} /></div>;
    })}</div>
  </>;
}

function PlansSection({ query, reloadKey, setAuthRequired, openModal, runAction, show }: any) {
  const plans = useApi<PlansApi>('/admin/api/v2/plans', reloadKey, setAuthRequired);
  const cats = useApi<ApiList<CategoryItem>>('/admin/api/v2/categories', reloadKey, setAuthRequired);
  const srvs = useApi<ApiList<ServerItem>>('/admin/api/v2/servers', reloadKey, setAuthRequired);
  const [publicOrder, setPublicOrder] = useState<PlanItem[]>([]);
  const [resellerOrder, setResellerOrder] = useState<ResellerPackage[]>([]);
  const [dragging, setDragging] = useState<{ kind: 'public' | 'reseller'; id: number } | null>(null);
  const [savingOrder, setSavingOrder] = useState('');

  useEffect(() => {
    if (!plans.data) return;
    setPublicOrder(plans.data.plans || []);
    setResellerOrder(plans.data.reseller_packages || []);
  }, [plans.data]);

  if (plans.loading || cats.loading || srvs.loading) return <SkeletonGrid />;
  if (plans.error || !plans.data) return <EmptyState message={plans.error || 'Plans could not be loaded.'} />;
  const catOpts = categoryOptions(cats.data?.items || []);
  const serverItems = srvs.data?.items || [];
  const srvOpts = serverOptions(serverItems);
  const publicPlans = filterItems(publicOrder, query, ['title']);
  const resellerPlans = filterItems(resellerOrder, query, ['title']);

  function reorderList<T extends { id: number }>(list: T[], fromId: number, toId: number) {
    const next = [...list];
    const from = next.findIndex((x) => x.id === fromId);
    const to = next.findIndex((x) => x.id === toId);
    if (from < 0 || to < 0 || from === to) return next;
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    return next;
  }

  async function saveOrder(kind: 'public' | 'reseller', list: { id: number }[]) {
    setSavingOrder(kind);
    try {
      await submitForm('/admin/plans/reorder', { kind, ids: list.map((x) => x.id).join(',') });
      show(kind === 'public' ? 'Public plan order saved' : 'Reseller plan order saved', true);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg === 'AUTH_REQUIRED') setAuthRequired(true);
      show(msg === 'AUTH_REQUIRED' ? 'Please login again' : msg, false);
    } finally {
      setSavingOrder('');
    }
  }

  function onDropPlan(kind: 'public' | 'reseller', targetId: number) {
    if (!dragging || dragging.kind !== kind) return;
    if (kind === 'public') {
      const next = reorderList(publicOrder, dragging.id, targetId);
      setPublicOrder(next);
      saveOrder('public', next);
    } else {
      const next = reorderList(resellerOrder, dragging.id, targetId);
      setResellerOrder(next);
      saveOrder('reseller', next);
    }
    setDragging(null);
  }

  return <>
    <div className="filterbar">
      <div className="actions"><button className="btn primary" onClick={() => openModal(planForm(catOpts, serverItems))}><Plus size={16} /> Add Plan</button></div>
      <span className="badge">{publicPlans.length + resellerPlans.length} plans</span>
    </div>
    <div className="plan-order-note"><ListChecks size={16} /> Drag and drop cards to change the order shown inside the Telegram bot sales list. {savingOrder && <b>Saving...</b>}</div>
    <div className="plan-columns">
      <section className="plan-order-panel">
        <div className="panel-head"><h2>Public Plans Order</h2><span className="badge green">Bot Sales</span></div>
        <div className="section-grid plan-sort-grid">
          {publicPlans.map((p) => <div key={`p${p.id}`} className={`drag-card ${dragging?.id === p.id && dragging.kind === 'public' ? 'dragging' : ''}`} draggable onDragStart={() => setDragging({ kind: 'public', id: p.id })} onDragOver={(e) => e.preventDefault()} onDrop={() => onDropPlan('public', p.id)} onDragEnd={() => setDragging(null)}><EntityCard title={p.title} icon={<Package />} badge={p.is_active ? 'Public / Active' : 'Public / Inactive'} badgeClass={p.is_active ? 'green' : 'red'} kvs={[["Price", toman(p.price_irt)], ['Volume', `${p.volume_gb} GB`], ['Duration', `${p.duration_days} days`], ['Server', p.server_id || '-'], ['Category', p.category_id || '-'], ['Inbound mode', p.inbound_mode === 'manual' ? 'Manual' : 'Automatic'], ['Inbounds', p.inbound_mode === 'manual' ? (p.inbound_ids?.length || 0) : 'All active']]} actions={<><span className="drag-handle"><ListChecks size={15} /> Drag</span><button className="btn" onClick={() => openModal(planForm(catOpts, serverItems, p))}>Edit</button><button className={p.is_active ? 'btn danger' : 'btn success'} onClick={() => runAction(`/admin/toggle/plans/${p.id}`, p.is_active ? 'Plan deactivated' : 'Plan activated')}>{p.is_active ? 'Deactivate' : 'Activate'}</button><button className="btn danger" onClick={() => runAction(`/admin/plans/${p.id}/delete`, 'Plan deleted')}>Delete</button></>} /></div>)}
        </div>
      </section>
      <section className="plan-order-panel">
        <div className="panel-head"><h2>Reseller Plans Order</h2><span className="badge purple">Reseller Menu</span></div>
        <div className="section-grid plan-sort-grid">
          {resellerPlans.map((p) => <div key={`r${p.id}`} className={`drag-card ${dragging?.id === p.id && dragging.kind === 'reseller' ? 'dragging' : ''}`} draggable onDragStart={() => setDragging({ kind: 'reseller', id: p.id })} onDragOver={(e) => e.preventDefault()} onDrop={() => onDropPlan('reseller', p.id)} onDragEnd={() => setDragging(null)}><EntityCard title={p.title} icon={<ShieldCheck />} badge={p.is_active ? 'Reseller / Active' : 'Reseller / Inactive'} badgeClass={p.is_active ? 'purple' : 'red'} kvs={[["Price", toman(p.price_irt)], ['Volume', `${p.volume_gb} GB`], ['Validity', `${p.reseller_validity_days} days`], ['Server', p.server_id || '-']]} actions={<><span className="drag-handle"><ListChecks size={15} /> Drag</span><button className="btn" onClick={() => openModal(resellerPlanForm(srvOpts, p))}>Edit</button><button className={p.is_active ? 'btn danger' : 'btn success'} onClick={() => runAction(`/admin/toggle/reseller-plans/${p.id}`, p.is_active ? 'Reseller plan deactivated' : 'Reseller plan activated')}>{p.is_active ? 'Deactivate' : 'Activate'}</button><button className="btn danger" onClick={() => runAction(`/admin/plans/reseller/${p.id}/delete`, 'Reseller plan deleted')}>Delete</button></>} /></div>)}
        </div>
      </section>
    </div>
  </>;
}

function PaymentsSection({ query, reloadKey, setAuthRequired, openModal, runAction }: any) {
  const payments = useApi<ApiList<PaymentItem>>('/admin/api/v2/payments', reloadKey, setAuthRequired);
  const srvs = useApi<ApiList<ServerItem>>('/admin/api/v2/servers', reloadKey, setAuthRequired);
  if (payments.loading || srvs.loading) return <SkeletonGrid />;
  if (payments.error || !payments.data) return <EmptyState message={payments.error || 'Payments could not be loaded.'} />;
  const srvOpts = serverOptions(srvs.data?.items || []);
  const rows = filterItems(payments.data.items, query, ['owner_name', 'card_number', 'server_type']);
  return <><div className="filterbar"><button className="btn primary" onClick={() => openModal(paymentForm(srvOpts))}><Plus size={16} /> Add Payment</button><span className="badge">{rows.length} accounts</span></div><div className="section-grid">{rows.map((p) => <EntityCard key={p.id} title={p.owner_name} icon={<CreditCard />} badge={p.server_type === 'reseller' ? 'Reseller' : 'Public'} badgeClass={p.is_active ? 'green' : 'red'} kvs={[["Card / Account", p.card_number], ['Server Type', p.server_type], ['Server ID', p.server_id || '-']]} actions={<><button className="btn" onClick={() => openModal(paymentForm(srvOpts, p))}>Edit</button><button className="btn danger" onClick={() => runAction(`/admin/payments/${p.id}/delete`, 'Payment account deleted')}>Delete</button></>} />)}</div></>;
}

function DiscountsSection({ query, reloadKey, setAuthRequired, openModal, runAction }: any) {
  const discounts = useApi<ApiList<DiscountItem>>('/admin/api/v2/discounts', reloadKey, setAuthRequired);
  const srvs = useApi<ApiList<ServerItem>>('/admin/api/v2/servers', reloadKey, setAuthRequired);
  if (discounts.loading || srvs.loading) return <SkeletonGrid />;
  if (discounts.error || !discounts.data) return <EmptyState message={discounts.error || 'Discounts could not be loaded.'} />;
  const rows = filterItems(discounts.data.items, query, ['code', 'discount_type']);
  const srvOpts = serverOptions(srvs.data?.items || []);
  return <><div className="filterbar"><button className="btn primary" onClick={() => openModal(discountForm(srvOpts))}><Plus size={16} /> Add Discount</button><span className="badge">{rows.length} codes</span></div><div className="section-grid">{rows.map((d) => {
    const scope = d.allowed_server_names?.length ? d.allowed_server_names.join(', ') : 'All servers';
    return <EntityCard key={d.id} title={d.code} icon={<Tag />} badge={d.is_active ? 'Active' : 'Inactive'} badgeClass={d.is_active ? 'green' : 'red'} kvs={[["Type", d.discount_type === 'percent' ? 'Percent' : 'Toman'], ['Value', d.discount_type === 'percent' ? `${d.value}%` : toman(d.value)], ['Usage', `${d.used_count}/${d.max_uses}`], ['Per User', d.per_user_limit], ['Allowed servers', scope], ['Expires', shortDate(d.expires_at)]]} actions={<><button className="btn" onClick={() => openModal(discountForm(srvOpts, d))}>Edit</button><button className="btn danger" onClick={() => runAction(`/admin/discounts/${d.id}/delete`, 'Discount deleted')}>Delete</button></>} />;
  })}</div></>;
}

function ResellersSection({ query, reloadKey, setAuthRequired, openModal, runAction, show }: any) {
  const { data, loading, error, setData } = useApi<ApiList<ResellerItem>>('/admin/api/v2/resellers', reloadKey, setAuthRequired);
  const [selected, setSelected] = useState<ResellerItem | null>(null);
  const [refreshingId, setRefreshingId] = useState<number | null>(null);

  async function refreshReseller(rid: number) {
    setRefreshingId(rid);
    try {
      const result: any = await getAction(`/admin/resellers/${rid}/refresh`);
      const fresh = await fetchJson<ApiList<ResellerItem>>('/admin/api/v2/resellers');
      setData(fresh);
      const updated = fresh.items.find((x) => x.id === rid) || null;
      if (selected?.id === rid && updated) setSelected(updated);
      show(result?.message || 'Reseller accounting refreshed', true);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg === 'AUTH_REQUIRED') setAuthRequired(true);
      show(msg === 'AUTH_REQUIRED' ? 'Please login again' : msg, false);
    } finally {
      setRefreshingId(null);
    }
  }
  if (loading) return <SkeletonGrid />;
  if (error || !data) return <EmptyState message={error || 'Resellers could not be loaded.'} />;
  const rows = filterItems(data.items, query, ['user.full_name', 'user.username', 'user.telegram_id']);
  if (selected) return <ResellerServicesLetter reseller={selected} reloadKey={reloadKey} setAuthRequired={setAuthRequired} onClose={() => setSelected(null)} />;
  return <>
    <div className="filterbar"><button className="btn primary" onClick={() => openModal(resellerForm())}><Plus size={16} /> Add Reseller</button><span className="badge">{rows.length} resellers</span></div>
    <div className="section-grid">{rows.map((r) => { const remain = Number(r.remaining_bytes ?? Number(r.total_bytes || 0)); return <EntityCard key={r.id} title={r.user.full_name || r.user.username || String(r.user.telegram_id)} icon={<UserCog />} badge={r.is_active ? 'Active' : 'Inactive'} badgeClass={r.is_active ? 'green' : 'red'} kvs={[["Telegram ID", r.user.telegram_id], ['Total', gbFromBytes(r.total_bytes)], ['Used', gbFromBytes(r.used_bytes)], ['Reserved', gbFromBytes(r.reserved_bytes)], ['Remaining', gbFromBytes(remain)], ['Expires', shortDate(r.expires_at)]]} actions={<><button className="btn success" disabled={refreshingId === r.id} onClick={() => refreshReseller(r.id)}><RefreshCw size={15} className={refreshingId === r.id ? 'spin' : ''} /> {refreshingId === r.id ? 'Refreshing' : 'Refresh Stats'}</button><button className="btn" onClick={() => setSelected(r)}><FileText size={15} /> List</button><button className="btn" onClick={() => openModal(resellerForm(r))}>Edit</button><button className="btn danger" onClick={() => runAction(`/admin/resellers/${r.id}/delete`, 'Reseller deleted')}>Delete</button></>} />; })}</div>
  </>;
}

function ResellerServicesLetter({ reseller, reloadKey, setAuthRequired, onClose }: { reseller: ResellerItem; reloadKey: number; setAuthRequired: (v: boolean) => void; onClose: () => void }) {
  const { data, loading, error } = useApi<ResellerServicesApi>(`/admin/api/v2/resellers/${reseller.id}/services`, reloadKey, setAuthRequired);
  const items = data?.items || [];
  const account = data?.reseller || reseller;
  const activeCount = items.filter((x) => x.is_active).length;
  const accountRemaining = Number(account.remaining_bytes ?? Number(account.total_bytes || 0));
  return <section className="card reseller-letter reseller-letter-page">
    <div className="letter-flap" />
    <div className="panel-head letter-head">
      <div>
        <h2>List | {reseller.user.full_name || reseller.user.username || reseller.user.telegram_id}</h2>
        <p className="muted">@{reseller.user.username || '-'} · Telegram ID: {reseller.user.telegram_id}</p>
      </div>
      <button className="btn ghost" onClick={onClose}><X size={16} /> Back</button>
    </div>
    <div className="letter-summary">
      <div><b>{gbFromBytes(account.total_bytes)}</b><span>Total</span></div>
      <div><b>{gbFromBytes(account.used_bytes)}</b><span>Used</span></div>
      <div><b>{gbFromBytes(account.reserved_bytes)}</b><span>Reserved</span></div>
      <div><b>{gbFromBytes(accountRemaining)}</b><span>Remaining</span></div>
      <div><b>{items.length}</b><span>Total configs</span></div>
      <div><b>{activeCount}</b><span>Active configs</span></div>
    </div>
    {loading ? <p className="muted">Loading reseller configs...</p> : error ? <EmptyState message={error} /> : <div className="table-scroll letter-table"><table><thead><tr><th>Username</th><th>Created</th><th>Used</th><th>Total</th><th>Remaining</th><th>Usage</th><th>Expires</th><th>Server</th><th>Status</th></tr></thead><tbody>{items.length ? items.map((svc) => <tr key={svc.id}><td><b>{svc.username}</b><div className="muted">#{svc.id}</div></td><td>{shortDate(svc.created_at)}</td><td>{gbFromBytes(svc.used_bytes)}</td><td>{gbFromBytes(svc.total_bytes)}</td><td>{gbFromBytes(svc.remaining_bytes)}</td><td><div className="usage-cell"><span>{Number(svc.used_percent || 0).toFixed(1)}%</span><div className="usage-track"><i style={{ width: `${Math.min(100, Math.max(0, Number(svc.used_percent || 0)))}%` }} /></div></div></td><td>{shortDate(svc.expires_at)}</td><td>{svc.server_name || '-'}</td><td><span className={`badge ${svc.is_active ? 'green' : 'red'}`}>{svc.is_active ? 'Active' : (svc.disabled_reason || 'Inactive')}</span></td></tr>) : <tr><td colSpan={9}><EmptyInline /></td></tr>}</tbody></table></div>}
  </section>;
}

function OrdersSection({ query, reloadKey, setAuthRequired, dateRange }: any) {
  const path = `/admin/api/v2/orders?page=1&page_size=150&start_date=${encodeURIComponent(dateRange.start)}&end_date=${encodeURIComponent(dateRange.end)}`;
  const { data, loading, error } = useApi<ApiList<OrderItem>>(path, reloadKey, setAuthRequired);
  if (loading) return <SkeletonGrid />;
  if (error || !data) return <EmptyState message={error || 'Orders could not be loaded.'} />;
  const rows = filterItems(data.items, query, ['status', 'payment_method', 'user.full_name', 'user.username', 'plan.title']);
  return <DataTable title={`Orders (${money(data.total || rows.length)})`} columns={['Order', 'User', 'Plan', 'Amount', 'Payment', 'Status', 'Rejection reason', 'Date']} rows={rows.map((o) => [`#ORD-${o.id}`, o.user?.full_name || o.user?.username || o.user?.telegram_id || '-', orderPlanTitle(o), toman(o.amount_irt), paymentLabel(o.payment_method), <span key="s" className={`badge ${statusClass(o.status)}`}>{o.status}</span>, o.rejection_reason || '-', shortDate(o.rejected_at || o.created_at)])} />;
}

function SettingsSection({ reloadKey, setAuthRequired, openModal, show }: any) {
  const { data, loading, error } = useApi<ApiList<SettingItem>>('/admin/api/v2/settings', reloadKey, setAuthRequired);
  if (loading) return <SkeletonGrid />;
  if (error || !data) return <EmptyState message={error || 'Settings could not be loaded.'} />;
  const map = Object.fromEntries(data.items.map((s) => [s.key, s.value]));
  async function applySsl() {
    if (!window.confirm('Apply SSL and restart both website/API and bot after success?')) return;
    try {
      const result: any = await getAction('/admin/settings/ssl/apply');
      show(result?.message || 'SSL applied. Website and bot restart requested.', true);
      window.setTimeout(() => window.location.reload(), 2600);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg === 'AUTH_REQUIRED') setAuthRequired(true);
      show(msg === 'AUTH_REQUIRED' ? 'Please login again' : msg, false);
    }
  }
  return <div className="section-grid"><EntityCard title="Bot Texts & Database" icon={<Database />} badge={map.bot_enabled === '0' ? 'Bot Off' : 'Bot On'} badgeClass={map.bot_enabled === '0' ? 'red' : 'green'} kvs={[["Start Text", map.welcome_text ? `${map.welcome_text.slice(0, 64)}...` : '-'], ['Rules Text', map.rules_text ? `${map.rules_text.slice(0, 64)}...` : '-'], ['Bot Status', map.bot_enabled === '0' ? 'Disabled' : 'Enabled'], ['Database Info', map.database_info || 'Connected']]} actions={<button className="btn primary" onClick={() => openModal(settingsBotCoreForm(map))}><Save size={16} /> Edit Bot Core</button>} /><EntityCard title="General Settings" icon={<Settings />} badge="Bot" kvs={[["Bot Name", map.bot_name || 'D BOT'], ['Support', map.support_username || '-'], ['Description', map.admin_description || '-']]} actions={<button className="btn primary" onClick={() => openModal(settingsGeneralForm(map))}>Edit General</button>} /><EntityCard title="Website & SSL" icon={<Home />} badge={map.web_ssl_status === 'active' ? 'SSL Active' : map.web_ssl_status === 'error' ? 'SSL Error' : 'SSL Pending'} badgeClass={map.web_ssl_status === 'active' ? 'green' : map.web_ssl_status === 'error' ? 'red' : 'yellow'} kvs={[["Domain", map.web_domain || '-'], ['Username', map.web_admin_username || '-'], ['Session', `${map.web_token_timeout_minutes || 30} min`], ['SSL status', map.web_ssl_status || 'not configured'], ['SSL message', map.web_ssl_message || '-'], ['Restart status', map.web_restart_status || '-'], ['Restart message', map.web_restart_message || '-']]} actions={<><button className="btn primary" onClick={() => openModal(settingsWebsiteForm(map))}>Edit Website</button><button className="btn success" onClick={applySsl}>Apply SSL</button></>} /><section className="card table-card" style={{ gridColumn: '1/-1' }}><div className="panel-head"><h2>Settings Table</h2><span className="badge">Protected values are hidden</span></div><div className="table-scroll"><table><thead><tr><th>Key</th><th>Value</th></tr></thead><tbody>{data.items.map((s) => <tr key={s.key}><td>{s.key}</td><td>{s.value}</td></tr>)}</tbody></table></div></section></div>;
}



function BackupSection({ reloadKey, setAuthRequired, show }: any) {
  const { data, loading, error, setData } = useApi<BackupSettings>('/admin/api/v2/backup/settings', reloadKey, setAuthRequired);
  const [form, setForm] = useState<BackupFormState>({ destination: 'channel', bot_token: '', chat_id: '', bot_username: '', time: '03:00', include_database: '1', include_files: '1' });
  const [test, setTest] = useState<BackupTestState>({ status: 'idle', message: '' });
  const [restoreFile, setRestoreFile] = useState<File | null>(null);
  const [busy, setBusy] = useState('');
  useEffect(() => {
    if (!data?.settings) return;
    setForm({
      destination: data.settings.backup_destination || 'channel',
      bot_token: data.settings.backup_bot_token || '',
      chat_id: data.settings.backup_chat_id || data.settings.backup_channel || '',
      bot_username: data.settings.backup_bot_username || '',
      time: data.settings.backup_time || '03:00',
      include_database: data.settings.backup_include_database || '1',
      include_files: data.settings.backup_include_files || '1'
    });
    if (data.status?.last_test_status) setTest({ status: data.status.last_test_status === 'ok' ? 'ok' : 'bad', message: data.status.last_test_message || '', adminOk: data.status.admin_ok });
  }, [data]);
  function setField(name: keyof BackupFormState, value: string) { setForm((prev) => ({ ...prev, [name]: value })); }
  async function saveSettings() {
    setBusy('save');
    try {
      await submitForm('/admin/backup/save', form);
      show('Backup settings saved', true);
      const fresh = await fetchJson<BackupSettings>('/admin/api/v2/backup/settings');
      setData(fresh);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg === 'AUTH_REQUIRED') setAuthRequired(true);
      show(msg === 'AUTH_REQUIRED' ? 'Please login again' : msg, false);
    } finally { setBusy(''); }
  }
  async function testDestination() {
    setBusy('test');
    try {
      const res: any = await submitForm('/admin/backup/test', form);
      setTest({ status: res.admin_ok === false ? 'bad' : 'ok', message: res.message || 'Test completed', adminOk: res.admin_ok });
      show(res.message || 'Backup destination tested', res.admin_ok !== false);
      const fresh = await fetchJson<BackupSettings>('/admin/api/v2/backup/settings');
      setData(fresh);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setTest({ status: 'bad', message: msg });
      show(msg, false);
    } finally { setBusy(''); }
  }
  async function runBackup() {
    setBusy('backup');
    try {
      await getAction('/admin/backup/run');
      show('Manual backup created and sent', true);
      const fresh = await fetchJson<BackupSettings>('/admin/api/v2/backup/settings');
      setData(fresh);
    } catch (err) { show(err instanceof Error ? err.message : String(err), false); } finally { setBusy(''); }
  }
  async function restoreBackup() {
    if (!restoreFile) { show('Choose a JSON backup file first', false); return; }
    if (!window.confirm('Restore this backup? Current database data will be synchronized with the backup file.')) return;
    setBusy('restore');
    try {
      const fd = new FormData();
      fd.append('file', restoreFile);
      const res = await fetch('/admin/backup/restore', { method: 'POST', body: fd, credentials: 'include', headers: adminCsrfHeaders() });
      const json = await res.json().catch(() => null);
      if (!res.ok || !json?.ok) throw new Error(json?.message || 'Restore failed');
      show(json.message || 'Backup restored', true);
      setRestoreFile(null);
    } catch (err) { show(err instanceof Error ? err.message : String(err), false); } finally { setBusy(''); }
  }
  if (loading) return <SkeletonGrid />;
  if (error || !data) return <EmptyState message={error || 'Backup settings could not be loaded.'} />;
  const status = data.status || { configured: false };
  const destinationLabel = form.destination === 'channel' ? 'Telegram Channel' : form.destination === 'group' ? 'Telegram Group' : 'Backup Bot';
  return <div className="section-grid backup-grid">
    <section className="card backup-settings-card">
      <div className="panel-head"><h2>Backup Destination</h2><span className={`badge ${status.configured ? 'green' : 'yellow'}`}>{status.configured ? 'Configured' : 'Not configured'}</span></div>
      <div className="form-grid compact-form">
        <label className="form-field"><span>Send backup to</span><select value={form.destination} onChange={(e) => setField('destination', e.target.value)}><option value="channel">Channel</option><option value="group">Group</option><option value="bot">Bot</option></select></label>
        <label className="form-field"><span>Backup time</span><input type="time" value={form.time} onChange={(e) => setField('time', e.target.value)} /></label>
        {form.destination === 'channel' && <label className="form-field full"><span>Channel link</span><input value={form.chat_id} onChange={(e) => setField('chat_id', e.target.value)} placeholder="@channel or https://t.me/channel" /></label>}
        {form.destination === 'group' && <label className="form-field full"><span>Group Link</span><input value={form.chat_id} onChange={(e) => setField('chat_id', e.target.value)} placeholder="@group, https://t.me/group, or -100..." /></label>}
        {form.destination === 'bot' && <label className="form-field full"><span>Bot token for sending backup</span><input type="password" value={form.bot_token} onChange={(e) => setField('bot_token', e.target.value)} placeholder="Backup bot token" /></label>}
        <label className="form-field"><span>Database backup</span><select value={form.include_database} onChange={(e) => setField('include_database', e.target.value)}><option value="1">Enabled</option><option value="0">Disabled</option></select></label>
        <label className="form-field"><span>Files backup</span><select value={form.include_files} onChange={(e) => setField('include_files', e.target.value)}><option value="1">Enabled</option><option value="0">Disabled</option></select></label>
      </div>
      <div className="card-actions"><button className="btn primary" disabled={busy === 'save'} onClick={saveSettings}><Save size={16} /> Save</button><button className="btn success" disabled={busy === 'test'} onClick={testDestination}><CheckCircle2 size={16} /> Test {destinationLabel}</button><button className="btn" disabled={busy === 'backup'} onClick={runBackup}><Archive size={16} /> Run Manual Backup</button></div>
      <div className={`backup-test-result ${test.status}`}><span>{test.status === 'ok' ? <CheckCircle2 size={18} /> : test.status === 'bad' ? <XCircle size={18} /> : <Bot size={18} />}</span><b>{test.status === 'idle' ? 'No test yet' : test.adminOk === false ? 'Admin access failed' : 'Test result'}</b><p>{test.message || 'Use Test to verify bot access and admin permission for channel/group.'}</p></div>
    </section>
    <EntityCard title="Backup Status" icon={<Archive />} badge={status.last_backup_status === 'ok' ? 'Last backup OK' : status.last_backup_status === 'error' ? 'Last backup error' : 'Ready'} badgeClass={status.last_backup_status === 'ok' ? 'green' : status.last_backup_status === 'error' ? 'red' : 'purple'} kvs={[["Destination", destinationLabel], [form.destination === 'channel' ? 'Channel link' : form.destination === 'group' ? 'Group Link' : 'Bot token', form.destination === 'bot' ? (form.bot_token ? 'Configured' : '-') : (form.chat_id || '-')], ['Last backup', status.last_backup_at ? shortDate(status.last_backup_at) : '-'], ['Last message', status.last_backup_message || '-']]} actions={<a className="btn" href="/admin/backup/download"><Download size={15} /> Download JSON</a>} />
    <section className="card restore-card">
      <div className="panel-head"><h2>Restore Local Backup</h2><span className="badge yellow">Website and Bot</span></div>
      <p className="muted">Upload a D BOT JSON backup from your computer. The system synchronizes database tables with the backup structure, restores data, and resets database sequences.</p>
      <label className="restore-drop"><Upload size={28} /><b>{restoreFile ? restoreFile.name : 'Choose backup file'}</b><small>JSON only · created from Backup & Restore</small><input type="file" accept="application/json,.json" onChange={(e) => setRestoreFile(e.target.files?.[0] || null)} /></label>
      <div className="card-actions"><button className="btn danger" disabled={!restoreFile || busy === 'restore'} onClick={restoreBackup}><Upload size={16} /> Restore & Sync</button></div>
    </section>
  </div>;
}


function TestAccountSection({ reloadKey, setAuthRequired, show }: any) {
  const { data, loading, error, setData } = useApi<TestAccountApi>('/admin/api/v2/test-account', reloadKey, setAuthRequired);
  const [form, setForm] = useState({ enabled: '1', button_visible: '1', server_id: '0', inbound_ids: '', volume_gb: '1', duration_days: '1' });
  const [saving, setSaving] = useState(false);
  const [deleteTelegramId, setDeleteTelegramId] = useState('');
  useEffect(() => {
    if (!data?.settings) return;
    setForm({
      enabled: data.settings.enabled || '1',
      button_visible: data.settings.button_visible || '1',
      server_id: data.settings.server_id || '0',
      inbound_ids: data.settings.inbound_ids || '',
      volume_gb: data.settings.volume_gb || '1',
      duration_days: data.settings.duration_days || '1'
    });
  }, [data]);
  if (loading) return <SkeletonGrid />;
  if (error || !data) return <EmptyState message={error || 'Test account settings could not be loaded.'} />;
  const selectedServer = data.servers.find((x) => String(x.id) === String(form.server_id));
  const availableInbounds = ((selectedServer?.inbounds?.length ? selectedServer.inbounds : (selectedServer?.inbound_ids || []).map((id: any) => ({ id: Number(typeof id === 'object' ? id.id : id), remark: `Inbound ${typeof id === 'object' ? id.id : id}`, protocol: '' }))) || []).filter((x: any) => Number(x.id) > 0);
  const selectedInboundIds = new Set(String(form.inbound_ids || '').split(/[\s,]+/).filter(Boolean).map((x) => Number(x)));
  const inboundCount = selectedInboundIds.size || availableInbounds.length;
  function toggleInbound(id: number) {
    const next = new Set(selectedInboundIds);
    if (next.has(id)) next.delete(id); else next.add(id);
    setForm({ ...form, inbound_ids: Array.from(next).sort((a, b) => a - b).join(',') });
  }
  function useAllInbounds() {
    setForm({ ...form, inbound_ids: availableInbounds.map((x: any) => Number(x.id)).filter(Boolean).join(',') });
  }
  async function save() {
    setSaving(true);
    try {
      await submitForm('/admin/test-account/save', form);
      const fresh = await fetchJson<TestAccountApi>('/admin/api/v2/test-account');
      setData(fresh);
      show('Test account settings saved', true);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg === 'AUTH_REQUIRED') setAuthRequired(true);
      show(msg === 'AUTH_REQUIRED' ? 'Please login again' : msg, false);
    } finally { setSaving(false); }
  }
  async function resetUsage() {
    if (!window.confirm('Reset test account usage history? Users will be able to receive a test account again.')) return;
    try {
      await getAction('/admin/test-account/reset-usages');
      const fresh = await fetchJson<TestAccountApi>('/admin/api/v2/test-account');
      setData(fresh);
      show('Usage history reset', true);
    } catch (err) { show(err instanceof Error ? err.message : String(err), false); }
  }
  async function deleteSingleUsage() {
    const tg = deleteTelegramId.trim();
    if (!tg) { show('Enter User Telegram ID first', false); return; }
    if (!/^\d+$/.test(tg)) { show('User Telegram ID must be numeric', false); return; }
    if (!window.confirm(`Remove test account usage for Telegram ID ${tg}? This user will be able to receive a test account again.`)) return;
    try {
      await getAction(`/admin/test-account/delete-usage?telegram_id=${encodeURIComponent(tg)}`);
      const fresh = await fetchJson<TestAccountApi>('/admin/api/v2/test-account');
      setData(fresh);
      setDeleteTelegramId('');
      show(`Test-account usage removed for ${tg}`, true);
    } catch (err) { show(err instanceof Error ? err.message : String(err), false); }
  }
  return <div className="section-grid test-account-grid">
    <section className="card test-account-hero">
      <div className="test-orb"><ShieldCheck size={34} /></div>
      <h2>Telegram Trial Account</h2>
      <p className="muted">This card controls the test account button in the bot. The bot creates one real X-UI client for each user based on these settings.</p>
      <div className="kvs">
        <div className="kv"><span>Status</span><b>{form.enabled === '1' ? 'Enabled' : 'Disabled'}</b></div>
        <div className="kv"><span>Button</span><b>{form.button_visible === '1' ? 'Visible' : 'Hidden'}</b></div>
        <div className="kv"><span>Server</span><b>{selectedServer?.display_name || selectedServer?.name || '-'}</b></div>
        <div className="kv"><span>Used by users</span><b>{data.usage_count}</b></div>
      </div>
      <div className="card-actions"><button className="btn danger" onClick={resetUsage}><Trash2 size={16} /> Reset usage history</button></div>
    </section>
    <section className="card test-account-settings">
      <div className="panel-head"><h2>Test Account Settings</h2><span className={`badge ${form.enabled === '1' ? 'green' : 'red'}`}>{form.enabled === '1' ? 'Active' : 'Inactive'}</span></div>
      <div className="form-grid">
        <label className="form-field"><span>Test account status</span><select value={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.value })}><option value="1">Enabled</option><option value="0">Disabled</option></select></label>
        <label className="form-field"><span>Bot button visibility</span><select value={form.button_visible} onChange={(e) => setForm({ ...form, button_visible: e.target.value })}><option value="1">Show button</option><option value="0">Hide button</option></select></label>
        <label className="form-field full"><span>Select server</span><select value={form.server_id} onChange={(e) => setForm({ ...form, server_id: e.target.value, inbound_ids: '' })}><option value="0">Select server</option>{data.servers.map((s) => <option key={s.id} value={s.id}>{s.display_name || s.name} · {s.server_type}</option>)}</select></label>
        <div className="form-field full"><span>Inbound IDs</span><div className="inbound-picker"><div className="inbound-toolbar"><button className="btn mini" type="button" onClick={useAllInbounds}>Select all</button><button className="btn mini" type="button" onClick={() => setForm({ ...form, inbound_ids: '' })}>Use all automatically</button></div>{availableInbounds.length ? availableInbounds.map((inb: any) => { const id = Number(inb.id); const active = selectedInboundIds.has(id) || (!form.inbound_ids && availableInbounds.length > 0); return <button type="button" key={id} className={`inbound-chip ${active ? 'selected' : ''}`} onClick={() => toggleInbound(id)}><b>#{id}</b><span>{inb.remark || `Inbound ${id}`}</span><small>{inb.protocol || 'x-ui'}</small></button>; }) : <p className="muted">No inbound found. Use Servers → Test & Update first.</p>}<input type="hidden" value={form.inbound_ids} readOnly /></div></div>
        <label className="form-field"><span>Volume GB</span><input type="number" min="0.1" step="0.1" value={form.volume_gb} onChange={(e) => setForm({ ...form, volume_gb: e.target.value })} /></label>
        <label className="form-field"><span>Duration days</span><input type="number" min="1" value={form.duration_days} onChange={(e) => setForm({ ...form, duration_days: e.target.value })} /></label>
      </div>
      <div className="test-summary"><div><b>{inboundCount}</b><span>Inbound IDs</span></div><div><b>{form.volume_gb} GB</b><span>Trial volume</span></div><div><b>{form.duration_days} days</b><span>Trial duration</span></div></div>
      <div className="card-actions"><button className="btn primary" disabled={saving} onClick={save}><Save size={16} /> Save Test Account</button></div>
    </section>
    <section className="card table-card test-usage-card">
      <div className="panel-head"><h2>Users who used test account</h2><span className="badge">{data.usage_count} total</span></div>
      <div className="filterbar compact-filter"><label className="form-field"><span>User Telegram ID</span><input value={deleteTelegramId} onChange={(e) => setDeleteTelegramId(e.target.value)} placeholder="Search and remove one user" /></label><button className="btn danger" onClick={deleteSingleUsage}><Search size={16} /> Remove this user</button></div>
      <div className="table-scroll"><table><thead><tr><th>User</th><th>Telegram ID</th><th>Service</th><th>Date</th><th>Action</th></tr></thead><tbody>{(data.usage_items || []).length ? (data.usage_items || []).map((u) => <tr key={u.id}><td>{u.user?.full_name || u.user?.username || '-'}</td><td>{u.telegram_id}</td><td>{u.service_id ? `#${u.service_id}` : '-'}</td><td>{shortDate(u.created_at)}</td><td><button className="btn mini danger" onClick={() => { setDeleteTelegramId(String(u.telegram_id)); }}><Trash2 size={14} /> Select</button></td></tr>) : <tr><td colSpan={5}><EmptyInline /></td></tr>}</tbody></table></div>
      <div className="card-actions"><button className="btn danger" onClick={resetUsage}><Trash2 size={16} /> Reset all test-account users</button></div>
    </section>
  </div>;
}

function ServiceTypesSection({ reloadKey, setAuthRequired, openModal, runAction, show }: any) {
  const { data, loading, error, setData } = useApi<ApiList<ServiceTypeItem>>('/admin/api/v2/service-types', reloadKey, setAuthRequired);
  const [dragKey, setDragKey] = useState<string>('');
  const [savingOrder, setSavingOrder] = useState(false);
  if (loading) return <SkeletonGrid />;
  if (error || !data) return <EmptyState message={error || 'Service types could not be loaded.'} />;
  const serviceTypes = data.items || [];
  async function saveOrder(items: ServiceTypeItem[]) {
    setSavingOrder(true);
    try {
      await submitForm('/admin/service-types/reorder', { keys: items.map((x) => x.key).join('|') });
      setData((prev) => ({ ...(prev ?? { ok: true, items: [] }), ok: prev?.ok ?? true, items }));
      show('Service type order saved', true);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg === 'AUTH_REQUIRED') setAuthRequired(true);
      show(msg === 'AUTH_REQUIRED' ? 'Please login again' : msg, false);
    } finally { setSavingOrder(false); }
  }
  function dropOn(targetKey: string) {
    if (!dragKey || dragKey === targetKey) return;
    const next = [...serviceTypes];
    const from = next.findIndex((x) => x.key === dragKey);
    const to = next.findIndex((x) => x.key === targetKey);
    if (from < 0 || to < 0) return;
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    setDragKey('');
    saveOrder(next);
  }
  return <><div className="filterbar"><button className="btn primary" onClick={() => openModal(serviceTypeForm())}><Plus size={16} /> Add Service Type</button><span className="badge">{serviceTypes.length} custom types</span>{savingOrder && <span className="badge yellow">Saving order...</span>}</div><div className="plan-order-note"><ListChecks size={16} /> Drag and drop service type cards to change bot display order. New service types are added at the bottom.</div><div className="section-grid">{serviceTypes.length ? serviceTypes.map((s) => <div key={s.key} className={`drag-card ${dragKey === s.key ? 'dragging' : ''}`} draggable onDragStart={() => setDragKey(s.key)} onDragOver={(e) => e.preventDefault()} onDrop={() => dropOn(s.key)} onDragEnd={() => setDragKey('')}><EntityCard title={s.value} icon={<ListChecks />} badge={s.is_active ? 'Active' : 'Inactive'} badgeClass={s.is_active ? 'green' : 'red'} kvs={[["Value", s.value], ['Display order', serviceTypes.findIndex((x) => x.key === s.key) + 1]]} actions={<><span className="drag-handle"><ListChecks size={15} /> Drag</span><button className="btn" onClick={() => openModal(serviceTypeForm(s))}>Edit</button><button className={s.is_active ? 'btn danger' : 'btn success'} onClick={() => runAction(`/admin/service-types/toggle?key=${encodeURIComponent(s.key)}`, s.is_active ? 'Service type deactivated' : 'Service type activated')}>{s.is_active ? 'Deactivate' : 'Activate'}</button><button className="btn danger" onClick={() => runAction(`/admin/service-types/delete?key=${encodeURIComponent(s.key)}`, 'Service type deleted')}>Delete</button></>} /></div>) : <EmptyState message="No custom service type found. Add V2Ray, OpenVPN, or any other service from here." />}</div></>;
}

function EntityCard({ title, icon, badge, badgeClass = 'purple', kvs, actions }: { title: string; icon: React.ReactNode; badge?: string; badgeClass?: string; kvs: [string, any][]; actions?: React.ReactNode }) {
  return <motion.section className="card entity-card" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} tabIndex={0}><div className="panel-head"><h3 className="row-left"><span className="tiny-avatar">{icon}</span>{title}</h3>{badge && <span className={`badge ${badgeClass}`}>{badge}</span>}</div><div className="kvs">{kvs.map(([k, v]) => <div className="kv" key={k}><span>{k}</span><b>{String(v ?? '-')}</b></div>)}</div>{actions && <div className="card-actions">{actions}</div>}</motion.section>;
}

function DataTable({ title, columns, rows }: { title: string; columns: string[]; rows: React.ReactNode[][] }) {
  return <section className="card table-card"><div className="panel-head"><h2>{title}</h2><span className="badge">{rows.length} rows</span></div><div className="table-scroll"><table><thead><tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr></thead><tbody>{rows.length ? rows.map((r, i) => <tr key={i}>{r.map((cell, j) => <td key={j}>{cell}</td>)}</tr>) : <tr><td colSpan={columns.length}><EmptyInline /></td></tr>}</tbody></table></div></section>;
}

function FormModal({ modal, onClose, onSubmit, show }: { modal: ModalForm; onClose: () => void; onSubmit: (values: Record<string, any>) => void; show: (m: string, good?: boolean) => void }) {
  const [values, setValues] = useState<Record<string, any>>(() => Object.fromEntries(modal.fields.map((f) => { const raw = modal.defaults?.[f.name]; return [f.name, Array.isArray(raw) ? raw.map(String).join(',') : String(raw ?? '')]; })));
  const [testing, setTesting] = useState(false);
  function change(name: string, value: any) {
    setValues((prev) => {
      const next = { ...prev, [name]: value };
      if (name === 'badge_color') next.badge_emoji = circleEmojiForColor(String(value || ''));
      if (name === 'server_id') next.inbound_ids = '';
      if (name === 'inbound_mode' && String(value) === 'automatic') next.inbound_ids = '';
      return next;
    });
  }
  function csvValues(name: string) { return String(values[name] || '').split(',').map((x) => x.trim()).filter(Boolean); }
  function toggleCsvValue(name: string, value: string, checked: boolean) { const current = new Set(csvValues(name)); if (checked) current.add(value); else current.delete(value); change(name, Array.from(current).join(',')); }
  function setAllMultiValues(field: FieldConfig) {
    const selected = fieldOptions(field).map((option) => String(option.value)).filter((value) => value !== '0');
    change(field.name, selected.join(','));
  }
  function submitCurrentForm(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const missingMulti = modal.fields.find((field) => field.type === 'multiselect' && field.required && visible(field) && csvValues(field.name).length === 0);
    if (missingMulti) {
      show(`Select at least one option for ${missingMulti.label}.`, false);
      return;
    }
    onSubmit(values);
  }
  function mergeUser(user: UserItem) { setValues((prev) => ({ ...prev, telegram_id: String(user.telegram_id), full_name: user.full_name || '', username: user.username || '' })); }
  function conditionMatches(condition: { name: string; value?: string; values?: string[] }) {
    let current = String(values[condition.name] || '');
    if (condition.name === '__selected_server_type') {
      const serverField = modal.fields.find((f) => f.name === 'server_id');
      const selectedServerId = String(values.server_id || '');
      const opt = serverField?.options?.find((o) => String(o.value) === selectedServerId);
      const label = String(opt?.label || '').toLowerCase();
      if (!selectedServerId || selectedServerId === '0') return false;
      current = label.includes('mikrotik') || label.includes('microtik') || label.includes('mikrotik / custom') ? 'mikrotik' : 'xui';
    }
    if (condition.values) return condition.values.includes(current);
    return current === condition.value;
  }
  function visible(field: FieldConfig) {
    if (field.showWhen && !conditionMatches(field.showWhen)) return false;
    if (field.showWhenAll && !field.showWhenAll.every(conditionMatches)) return false;
    return true;
  }
  function fieldOptions(field: FieldConfig) {
    if (!field.optionsBy) return field.options || [];
    return field.optionsBy.map[String(values[field.optionsBy.name] || '')] || [];
  }
  async function testServerConnection() {
    setTesting(true);
    try {
      const testPath = '/admin/servers/test';
      const result: any = await submitForm(testPath, values);
      if (result?.auto_fill && typeof result.auto_fill === 'object') {
        setValues((prev) => ({ ...prev, ...Object.fromEntries(Object.entries(result.auto_fill).map(([k, v]) => [k, String(v ?? '')])) }));
      }
      show(result?.message || 'Connection OK', true);
    } catch (err) {
      show(err instanceof Error ? err.message : String(err), false);
    } finally { setTesting(false); }
  }
  const isNewServer = modal.action === '/admin/servers/add' || modal.action.startsWith('/admin/servers/');
  return <div className="modal-backdrop"><motion.div className="modal-card" initial={{ scale: .96, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}><div className="modal-head"><h2>{modal.title}</h2><button className="icon-btn" onClick={onClose}><X size={18} /></button></div><form className="form-grid" onSubmit={submitCurrentForm}>{modal.fields.filter((f) => !f.hidden).filter(visible).map((field) => <label key={field.name} className={`form-field ${field.full ? 'full' : ''}`}><span>{field.label}</span>{field.type === 'user-search' ? <UserSearchField onPick={mergeUser} /> : field.type === 'textarea' ? <textarea required={field.required} placeholder={field.placeholder} value={values[field.name] || ''} onChange={(e) => change(field.name, e.target.value)} /> : field.type === 'checkbox-group' ? <div className="checkbox-grid">{fieldOptions(field).filter((o) => String(o.value) !== '0').map((o) => { const value = String(o.value); const checked = csvValues(field.name).includes(value); return <label key={value} className={`checkline ${checked ? 'checked' : ''}`}><input type="checkbox" checked={checked} onChange={(e) => toggleCsvValue(field.name, value, e.currentTarget.checked)} /><span className="checkmark" aria-hidden="true">{checked ? '✓' : ''}</span><span className="checktext">{o.label}</span></label>; })}</div> : field.type === 'multiselect' ? <div className="multi-picker"><div className="multi-picker-toolbar"><span className="multi-picker-count">{csvValues(field.name).length} selected</span><div className="multi-picker-actions"><button type="button" className="btn mini" onClick={() => setAllMultiValues(field)}>Select all</button><button type="button" className="btn mini" onClick={() => change(field.name, '')}>Clear all</button></div></div><div className="checkbox-grid multi-checkbox-grid">{fieldOptions(field).filter((o) => String(o.value) !== '0').map((o) => { const value = String(o.value); const checked = csvValues(field.name).includes(value); return <button type="button" key={value} role="checkbox" aria-checked={checked} className={`checkline multi-checkline ${checked ? 'checked' : ''}`} onClick={() => toggleCsvValue(field.name, value, !checked)}><span className="checkmark" aria-hidden="true">{checked ? '✓' : ''}</span><span className="checktext">{o.label}</span></button>; })}</div>{fieldOptions(field).length === 0 && <p className="muted multi-picker-empty">No inbound is available for the selected server. Run Servers → Test &amp; Auto Fill first.</p>}<input type="hidden" value={values[field.name] || ''} readOnly /></div> : field.type === 'select' ? <select required={field.required} value={values[field.name] || ''} onChange={(e) => change(field.name, e.target.value)}>{fieldOptions(field).map((o) => <option key={String(o.value)} value={String(o.value)}>{o.label}</option>)}</select> : field.type === 'file' ? <input type="file" required={field.required} accept={field.placeholder || '.ovpn'} onChange={(e) => change(field.name, e.target.files?.[0] || null)} /> : <input type={field.type || 'text'} required={field.required} placeholder={field.placeholder} value={values[field.name] || ''} onChange={(e) => change(field.name, e.target.value)} />}</label>)}<div className="form-actions">{isNewServer && <button type="button" className="btn success" disabled={testing} onClick={testServerConnection}><CheckCircle2 size={16} /> {testing ? 'Testing...' : 'Test & Auto Fill'}</button>}<button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn primary" type="submit">Save</button></div></form></motion.div></div>;
}

function UserSearchField({ onPick }: { onPick: (user: UserItem) => void }) {
  const [q, setQ] = useState('');
  const [items, setItems] = useState<UserItem[]>([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (q.trim().length < 2) { setItems([]); return; }
    let cancelled = false;
    setBusy(true);
    fetchJson<ApiList<UserItem>>(`/admin/api/v2/users?page=1&page_size=8&q=${encodeURIComponent(q)}`).then((res) => {
      if (!cancelled) setItems(res.items || []);
    }).catch(() => { if (!cancelled) setItems([]); }).finally(() => { if (!cancelled) setBusy(false); });
    return () => { cancelled = true; };
  }, [q]);
  return <div className="user-search"><div className="inline-input"><Search size={16} /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, numeric ID, or username" /></div>{busy && <div className="muted search-hint">Searching...</div>}{items.length > 0 && <div className="user-results">{items.map((u) => <button type="button" key={u.id} onClick={() => { onPick(u); setQ(u.full_name || u.username || String(u.telegram_id)); setItems([]); }}><span className="tiny-avatar">{firstLetter(u.full_name || u.username)}</span><span><b>{u.full_name || u.username || 'Unknown'}</b><small>@{u.username || '-'} · {u.telegram_id}</small></span></button>)}</div>}</div>;
}

function filterItems<T>(items: T[], query: string, keys: string[]) {
  const q = (query || '').toLowerCase().trim();
  if (!q) return items;
  return items.filter((item: any) => keys.some((key) => String(key.split('.').reduce((obj, part) => obj?.[part], item) ?? '').toLowerCase().includes(q)));
}
function serverOptions(items: ServerItem[]) { return [{ value: 0, label: 'Select server' }, ...items.map((s) => ({ value: s.id, label: `${s.display_name || s.name} (${s.server_type === 'mikrotik' ? 'MikroTik / Custom' : s.server_type})` }))]; }
function categoryOptions(items: CategoryItem[]) { return [{ value: 0, label: 'Select category' }, ...items.map((c) => ({ value: c.id, label: `${c.name}${c.server_names?.length ? ` (${c.server_names.join(', ')})` : (c.server_id ? ` (Server #${c.server_id})` : '')}` }))]; }
function commonScopeOptions() { return [{ value: 'public', label: 'Public sales' }, { value: 'reseller', label: 'Reseller' }, { value: 'all', label: 'Public + Reseller' }]; }

function serverForm(s?: ServerItem): ModalForm {
  const isCustom = s?.server_type === 'mikrotik';
  const defaults = s ? {
    ...s,
    server_type: isCustom ? 'mikrotik' : 'xui',
    scope: s.scope || (isCustom ? 'all' : 'public'),
    panel_url: isCustom ? (s.panel_base_url || s.panel_url || '') : (s.panel_base_url || s.panel_url || ''),
    panel_path: isCustom ? '/' : (s.panel_path || '/'),
    subscription_url: isCustom ? '' : (s.subscription_url || ''),
    username: isCustom ? (s.auth_username || '') : (s.username || ''),
    name: isCustom ? (s.name || 'custom-panel') : (s.name || ''),
    display_name: s.display_name || s.name || '',
    detected_routers: isCustom ? (s.router_name || '') : '',
    api_key: '',
    l2tp_server: s.l2tp_server || 'vpn.example.com',
    l2tp_ipsec_secret: s.l2tp_ipsec_secret || 'CHANGE_ME_IPSEC_SECRET',
    badge_color: s.badge_color || (isCustom ? '#f97316' : '#2563eb'),
    badge_emoji: circleEmojiForColor(s.badge_color || (isCustom ? '#f97316' : '#2563eb')),
    badge_label: s.badge_label || (isCustom ? 'MikroTik / OpenVPN' : 'V2Ray')
  } : {
    server_type: 'xui',
    scope: 'public',
    panel_url: '',
    panel_path: '/',
    subscription_url: '',
    username: '',
    password: '',
    name: '',
    display_name: '',
    detected_routers: '',
    api_key: '',
    l2tp_server: 'vpn.example.com',
    l2tp_ipsec_secret: 'CHANGE_ME_IPSEC_SECRET',
    badge_color: '#2563eb',
    badge_emoji: circleEmojiForColor('#2563eb'),
    badge_label: 'V2Ray'
  };
  return {
    title: s ? 'Edit Server' : 'Add Server',
    action: s ? `/admin/servers/${s.id}/edit` : '/admin/servers/add',
    defaults,
    fields: [
      { name: 'server_type', label: 'Profile', type: 'select', options: [{ value: 'xui', label: '3x-ui / Sanaei' }, { value: 'mikrotik', label: 'MikroTik / Custom' }] },
      { name: 'scope', label: 'Show this server for', type: 'select', options: commonScopeOptions() },
      { name: 'name', label: 'Server name shown to users', required: true, placeholder: 'Germany / DE / OpenVPN Germany' },
      { name: 'display_name', label: 'Display name', placeholder: 'Optional bot/admin display name' },
      { name: 'badge_label', label: 'Service badge text shown to users', placeholder: 'V2Ray or MikroTik / OpenVPN' },
      { name: 'badge_color', label: 'Circle color in website', type: 'color' },
      { name: 'badge_emoji', label: 'Circle emoji in bot (auto from color)', placeholder: 'Auto based on Circle color' },
      { name: 'panel_url', label: 'Panel URL / Origin', required: true, full: true, placeholder: 'https://panel.example.com' },
      { name: 'panel_path', label: 'Panel Web Path', placeholder: '/secretpath/', showWhen: { name: 'server_type', value: 'xui' } },
      { name: 'subscription_url', label: 'Subscription URL', full: true, placeholder: 'https://sub.example.com/sub/', showWhen: { name: 'server_type', value: 'xui' } },
      { name: 'username', label: 'Username (optional when API token is used)', required: false },
      { name: 'password', label: s ? 'New password / login password' : 'Password / login password', type: 'password', required: false },
      { name: 'api_key', label: 'API token / MikroTik API key', type: 'password', full: true, placeholder: 'For 3x-ui paste API token; for MikroTik paste api_key if needed' },
      { name: 'l2tp_server', label: 'L2TP server shown in guides', placeholder: 'vpn.example.com', showWhen: { name: 'server_type', value: 'mikrotik' } },
      { name: 'l2tp_ipsec_secret', label: 'L2TP Secret shown in guides', placeholder: 'CHANGE_ME_IPSEC_SECRET', showWhen: { name: 'server_type', value: 'mikrotik' } },
      { name: 'detected_routers', label: 'Detected routers', full: true, placeholder: 'Auto-filled after Test & Auto Fill', showWhen: { name: 'server_type', value: 'mikrotik' } }
    ]
  };
}

function categoryForm(options: any[], c?: CategoryItem): ModalForm {
  const selectedServers = c?.server_ids?.length ? c.server_ids : (c?.server_id ? [c.server_id] : []);
  return {
    title: c ? 'Edit Category' : 'Add Category',
    action: c ? `/admin/categories/${c.id}/edit` : '/admin/categories/add',
    defaults: c ? { ...c, server_ids: selectedServers } : { server_ids: [] },
    fields: [
      { name: 'name', label: 'Category name', required: true },
      { name: 'server_ids', label: 'Servers shown under this category', type: 'checkbox-group', options, full: true }
    ]
  };
}
function planForm(catOptions: any[], servers: ServerItem[], p?: PlanItem): ModalForm {
  const serverOptionsList = serverOptions(servers);
  const inboundOptionsByServer: Record<string, { value: string | number; label: string }[]> = {};
  for (const server of servers) {
    const rows = server.inbounds?.length ? server.inbounds : (server.inbound_ids || []).map((raw: any) => ({ id: Number(typeof raw === 'object' ? raw.id : raw), remark: '', protocol: '' }));
    inboundOptionsByServer[String(server.id)] = rows
      .filter((row: any) => Number(row.id) > 0 && row.enable !== false)
      .map((row: any) => ({ value: Number(row.id), label: `#${Number(row.id)} · ${row.remark || `Inbound ${Number(row.id)}`}${row.protocol ? ` (${row.protocol})` : ''}` }));
  }
  const inboundMode = p?.inbound_mode || 'automatic';
  return {
    title: p ? 'Edit Public Plan' : 'Add Plan',
    action: p ? `/admin/plans/${p.id}/edit` : '/admin/plans/add',
    defaults: p ? { ...p, plan_kind: 'public', inbound_mode: inboundMode } : { plan_kind: 'public', category_id: 0, server_id: 0, reseller_validity_days: 365, inbound_mode: 'automatic', inbound_ids: [] },
    fields: [
      { name: 'plan_kind', label: 'Plan is for', type: 'select', options: [{ value: 'public', label: 'Public' }, { value: 'reseller', label: 'Resellers' }], hidden: !!p },
      { name: 'title', label: 'Plan title', required: true },
      { name: 'price_irt', label: 'Price (Toman)', type: 'number', required: true },
      { name: 'volume_gb', label: 'Volume GB', type: 'number', required: true },
      { name: 'duration_days', label: 'Duration days', type: 'number', required: true, showWhen: { name: 'plan_kind', value: 'public' } },
      { name: 'reseller_validity_days', label: 'Reseller validity days', type: 'number', required: true, showWhen: { name: 'plan_kind', value: 'reseller' } },
      { name: 'category_id', label: 'Select category', type: 'select', options: catOptions, required: true, showWhen: { name: 'plan_kind', value: 'public' } },
      { name: 'server_id', label: 'Select server', type: 'select', options: serverOptionsList, required: true },
      { name: 'inbound_mode', label: 'Inbound selection mode', type: 'select', options: [{ value: 'automatic', label: 'Automatic — use all active server inbounds' }, { value: 'manual', label: 'Manual — choose specific inbounds' }], required: true, full: true, showWhenAll: [{ name: 'plan_kind', value: 'public' }, { name: '__selected_server_type', value: 'xui' }] },
      { name: 'inbound_ids', label: 'Inbounds included in this plan', type: 'multiselect', optionsBy: { name: 'server_id', map: inboundOptionsByServer }, required: true, full: true, showWhenAll: [{ name: 'plan_kind', value: 'public' }, { name: '__selected_server_type', value: 'xui' }, { name: 'inbound_mode', value: 'manual' }] }
    ]
  };
}
function resellerPlanForm(serverOptionsList: any[], p?: ResellerPackage): ModalForm { return { title: 'Edit Reseller Plan', action: p ? `/admin/plans/reseller/${p.id}/edit` : '/admin/plans/add', defaults: p ? { ...p, plan_kind: 'reseller' } : { plan_kind: 'reseller', reseller_validity_days: 365, server_id: 0 }, fields: [{ name: 'plan_kind', label: 'Plan is for', type: 'select', options: [{ value: 'public', label: 'Public' }, { value: 'reseller', label: 'Resellers' }], hidden: !!p }, { name: 'title', label: 'Plan title', required: true }, { name: 'price_irt', label: 'Price (Toman)', type: 'number', required: true }, { name: 'volume_gb', label: 'Volume GB', type: 'number', required: true }, { name: 'reseller_validity_days', label: 'Validity days', type: 'number', required: true }, { name: 'server_id', label: 'Select server', type: 'select', options: serverOptionsList, required: true, full: true }] }; }
function paymentForm(serverOptionsList: any[], p?: PaymentItem): ModalForm { return { title: p ? 'Edit Payment' : 'Add Payment', action: p ? `/admin/payments/${p.id}/edit` : '/admin/payments/add', defaults: p ? { ...p, show_for: p.server_type === 'reseller' ? 'reseller' : 'public' } : { show_for: 'public', server_id: 0 }, fields: [{ name: 'card_number', label: 'Card / account number', required: true }, { name: 'owner_name', label: 'Owner name', required: true }, { name: 'show_for', label: 'Where to show', type: 'select', options: [{ value: 'public', label: 'Public' }, { value: 'reseller', label: 'Reseller' }] }, { name: 'server_id', label: 'Server for public payment', type: 'select', options: serverOptionsList, full: true }] }; }
function discountForm(serverOptionsList: any[], d?: DiscountItem): ModalForm {
  const selectedServers = d?.allowed_server_ids?.length ? d.allowed_server_ids : [];
  return {
    title: d ? 'Edit Discount Code' : 'Add Discount Code',
    action: d ? `/admin/discounts/${d.id}/edit` : '/admin/discounts/add',
    defaults: d ? { ...d, allowed_server_ids: selectedServers } : { discount_type: 'percent', max_uses: 1, per_user_limit: 1, allowed_server_ids: [] },
    fields: [
      { name: 'code', label: 'Code', required: true },
      { name: 'discount_type', label: 'Discount type', type: 'select', options: [{ value: 'percent', label: 'Percent (%)' }, { value: 'fixed', label: 'Toman amount' }] },
      { name: 'value', label: 'Discount value', type: 'number', required: true, placeholder: '20 for percent or 50000 for Toman' },
      { name: 'max_uses', label: 'Max uses', type: 'number', required: true },
      { name: 'per_user_limit', label: 'Per user limit', type: 'number', required: true },
      { name: 'allowed_server_ids', label: 'Allowed servers for this discount', type: 'checkbox-group', options: serverOptionsList, full: true, placeholder: 'Leave empty to allow all servers' }
    ]
  };
}

function resellerForm(r?: ResellerItem): ModalForm {
  const expiryDate = r?.expires_at ? String(r.expires_at).slice(0, 10) : '';
  const defaults = r ? { total_gb: Math.round(r.total_bytes / 1024 ** 3), expires_at: expiryDate } : { total_gb: 0, days: 30 };
  return {
    title: r ? 'Edit Reseller' : 'Add Reseller',
    action: r ? `/admin/resellers/${r.id}/edit` : '/admin/resellers/add',
    defaults,
    fields: r ? [
      { name: 'total_gb', label: 'Total GB', type: 'number', required: true },
      { name: 'expires_at', label: 'Expiry date', type: 'date', required: false, full: true }
    ] : [
      { name: 'user_search', label: 'Find user from database', type: 'user-search', full: true },
      { name: 'telegram_id', label: 'Telegram numeric ID', type: 'number', required: true },
      { name: 'full_name', label: 'Full name' },
      { name: 'username', label: 'Telegram username' },
      { name: 'total_gb', label: 'Total GB', type: 'number' },
      { name: 'days', label: 'Remaining days', type: 'number' }
    ]
  };
}
function serviceTypeForm(s?: ServiceTypeItem): ModalForm { return { title: s ? 'Edit Service Type' : 'Add Service Type', action: s ? '/admin/service-types/edit' : '/admin/service-types/add', defaults: s ? { key: s.key, name: s.value } : {}, fields: [...(s ? [{ name: 'key', label: 'Key', type: 'text' as const, hidden: true }] : []), { name: 'name', label: 'Service name', required: true, full: true }] }; }
function settingsGeneralForm(map: Record<string, string>): ModalForm { return { title: 'General Settings', action: '/admin/settings/save', defaults: { bot_name: map.bot_name || 'D BOT', support: map.support_username || '@support', description: map.admin_description || '' }, fields: [{ name: 'bot_name', label: 'Bot name', required: true }, { name: 'support', label: 'Support username', required: true }, { name: 'description', label: 'Description', type: 'textarea', full: true }] }; }
function settingsBotCoreForm(map: Record<string, string>): ModalForm { return { title: 'Bot Texts, Status & Database', action: '/admin/settings/bot-core', defaults: { welcome_text: map.welcome_text || '', rules_text: map.rules_text || '', bot_enabled: map.bot_enabled || '1', database_info: map.database_info || 'Connected' }, fields: [{ name: 'welcome_text', label: 'Start text / Welcome text', type: 'textarea', required: true, full: true }, { name: 'rules_text', label: 'Rules text', type: 'textarea', required: true, full: true }, { name: 'bot_enabled', label: 'Bot status', type: 'select', options: [{ value: '1', label: 'Enabled' }, { value: '0', label: 'Disabled' }], required: true }, { name: 'database_info', label: 'Database info text', type: 'textarea', full: true }] }; }
function settingsWebsiteForm(map: Record<string, string>): ModalForm { return { title: 'Website Settings', action: '/admin/settings/website', defaults: { domain: map.web_domain || '', username: map.web_admin_username || '', token_timeout: map.web_token_timeout_minutes || 30 }, fields: [{ name: 'domain', label: 'Domain' }, { name: 'username', label: 'Username' }, { name: 'password', label: 'New password', type: 'password' }, { name: 'token_timeout', label: 'Token timeout minutes', type: 'number' }] }; }
function openvpnProfileForm(serverOptionsList: any[], p?: OpenVPNProfileItem): ModalForm { return { title: p ? 'Edit OpenVPN Profile' : 'Add OpenVPN Profile', action: p ? `/admin/openvpn-profiles/${p.id}/edit` : '/admin/openvpn-profiles/add', defaults: p || { server_id: 0, file_name: 'profile.ovpn' }, fields: [{ name: 'name', label: 'Profile name', required: true }, { name: 'server_id', label: 'Bind to MikroTik / Custom server', type: 'select', options: serverOptionsList }, { name: 'file_name', label: 'File name', required: true }, { name: 'file', label: 'Upload .ovpn file', type: 'file', placeholder: '.ovpn', full: true }, { name: 'content', label: 'OVPN content', type: 'textarea', required: !p, full: true, placeholder: 'Paste .ovpn file content here or upload a file above' }] }; }
function backupForm(): ModalForm { return { title: 'Backup Settings', action: '/admin/backup/save', defaults: { channel: '@dbot_backup_channel', time: '03:00' }, fields: [{ name: 'channel', label: 'Backup channel', required: true }, { name: 'time', label: 'Backup time', type: 'time', required: true }] }; }

function SkeletonGrid() { return <div className="cards4"><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div>; }
function EmptyState({ message }: { message: string }) { return <div className="empty">{message}</div>; }
function EmptyInline() { return <div className="muted">No items found.</div>; }
