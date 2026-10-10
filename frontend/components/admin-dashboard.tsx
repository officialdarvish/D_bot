'use client';

import { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Activity,
  Archive,
  ArrowRight,
  Bot,
  CheckCircle2,
  ChevronDown,
  CreditCard,
  Download,
  FileText,
  Gauge,
  Gift,
  Globe2,
  Github,
  Home,
  KeyRound,
  Layers3,
  LayoutDashboard,
  ListChecks,
  Languages,
  LogOut,
  Menu,
  Network,
  Package,
  Plus,
  RefreshCw,
  Router,
  Save,
  Search,
  Send,
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
  Waypoints,
  Wifi,
  Zap,
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
import { CustomSection } from '@/components/custom-section';
import { LanguageSwitch } from '@/lib/ui-language';

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
  | 'pasarguard-panel-sales'
  | 'plans'
  | 'payments'
  | 'discounts'
  | 'users'
  | 'resellers'
  | 'servers'
  | 'categories'
  | 'connection'
  | 'backup'
  | 'custom'
  | 'settings';

type DashboardApi = {
  ok: boolean;
  stats: Record<string, number>;
  resources: ResourceMetric[];
  chart_ranges: { range: number; data: { date: string; label: string; sales: number }[] }[];
  latest_orders: OrderItem[];
  revenue_cycle?: { start: string; end: string; next_reset_at: string; days: number };
};

type ResourceMetric = { title: string; value: string; detail: string; percent: number; icon: string; cls: string };
type UserItem = { id: number; telegram_id: number; username?: string; full_name?: string; wallet_total: number; purchases: number; referral_code?: string; joined_at?: string; is_blocked?: boolean; is_reseller?: boolean };
type ServerItem = { id: number; name: string; display_name?: string; server_type: string; server_type_label?: string; panel_url: string; panel_base_url?: string; panel_path?: string; subscription_url?: string; username: string; auth_username?: string; scope?: string; inbound_ids?: unknown[]; inbounds?: { id: number; remark?: string; protocol?: string; enable?: boolean }[]; client_groups?: { name: string; client_count?: number | null }[]; last_inbound_sync_at?: string; is_active: boolean; user_count?: number; router_name?: string; router_host?: string; router_port?: string | number; router_online?: boolean; router_identity?: string; router_version?: string; router_uptime?: string; router_secrets?: number; router_active?: number; router_error?: string; last_router_sync_at?: string; default_protocol?: string; openvpn_profile_id?: number; l2tp_server?: string; l2tp_ipsec_secret?: string; badge_color?: string; badge_emoji?: string; badge_label?: string; pasarguard_role_name?: string; pasarguard_restricted?: boolean; pasarguard_group_source?: string; pasarguard_group_ids?: number[]; pasarguard_require_template?: boolean; pasarguard_capabilities?: Record<string, any>; pasarguard_limits?: Record<string, any>; pasarguard_warnings?: string[] };
type CategoryItem = { id: number; name: string; server_id?: number | null; server_ids?: number[]; server_names?: string[]; is_active?: boolean };
type PlanItem = { id: number; title: string; volume_gb: number; duration_days: number; price_irt: number; pricing_currency?: 'IRT' | 'USD'; price_usd?: string; category_id?: number; server_id?: number; inbound_ids?: unknown[]; inbound_mode?: 'automatic' | 'manual'; group_name?: string; hwid_limit?: number; is_active: boolean; is_unlimited?: boolean };
type ServerGroupsApi = { ok: boolean; items: { server_id: number; groups: { name: string; client_count?: number | null }[]; error?: string }[] };
type ResellerPackage = { id: number; title: string; server_id?: number; volume_gb: number; price_irt: number; pricing_currency?: 'IRT' | 'USD'; price_usd?: string; reseller_validity_days: number; is_active: boolean };
type PaymentItem = { id: number; server_type: string; server_id?: number; card_number: string; owner_name: string; reviewer_telegram_id?: number | null; is_active: boolean };
type DiscountItem = { id: number; code: string; discount_type: string; value: number; max_uses: number; per_user_limit: number; used_count: number; expires_at?: string; is_active: boolean; allowed_server_ids?: number[]; allowed_server_names?: string[] };
type ResellerItem = { id: number; user: UserItem; server_id?: number | null; inbound_mode?: 'automatic' | 'manual'; inbound_ids?: number[]; group_name?: string; total_bytes: number; used_bytes: number; reserved_bytes: number; remaining_bytes?: number; expires_at?: string; is_active: boolean; created_at?: string };
type ResellerServiceItem = { id: number; username: string; panel_username?: string; server_id?: number | null; server_name?: string; server_type?: string; plan_title?: string; total_bytes: number; used_bytes: number; remaining_bytes: number; used_percent: number; expires_at?: string; created_at?: string; is_active: boolean; disabled_reason?: string };
type ResellerActivityItem = { id: number; action: string; action_label?: string; service_id?: number | null; username: string; server_id?: number | null; server_name?: string; volume_bytes: number; previous_volume_bytes?: number; duration_days?: number; expires_at?: string; created_at?: string; released_bytes?: number; old_used_bytes?: number; old_unused_bytes?: number; added_bytes?: number; deducted_bytes?: number; requested_volume_bytes?: number; quota_before_bytes?: number; quota_after_bytes?: number; quota_remaining_after_bytes?: number; quota_delta_bytes?: number; quota_snapshot_version?: number; service_total_before_bytes?: number; service_total_after_bytes?: number; status?: string; error_type?: string; error_message?: string; failure_stage?: string; operation_id?: string; request_id?: number | null; package_title?: string; legacy_quota_snapshot_unavailable?: boolean; source?: string };
type ResellerServicesApi = { ok: boolean; reseller: ResellerItem; items: ResellerServiceItem[]; activities?: ResellerActivityItem[]; total: number; activity_total?: number };
type OrderItem = { id: number; user?: UserItem | null; plan?: PlanItem | null; amount_irt: number; status: string; payment_method?: string; rejection_reason?: string | null; rejected_by?: number | null; rejected_at?: string | null; receipt_file_id?: string | null; created_at?: string };
type SettingItem = { key: string; value: string; is_active?: boolean };
type ServiceTypeItem = { key: string; value: string; is_active: boolean; server_type?: 'xui' | 'pasarguard' | 'mikrotik'; server_type_mode?: 'auto' | 'manual' };
type BackupSettings = { ok: boolean; settings: Record<string, string>; status: { configured: boolean; last_test_status?: string; last_test_message?: string; last_backup_status?: string; last_backup_message?: string; last_backup_at?: string; admin_ok?: boolean; last_sales_report_status?: string; last_sales_report_message?: string; last_sales_report_at?: string; last_sales_report_period_start?: string; last_sales_report_period_end?: string } };
type BackupFormState = { destination: string; sender_mode: string; secondary_bot_token: string; chat_id: string; interval_minutes: string; include_database: string; include_files: string };
type BackupTestState = { status: 'idle' | 'ok' | 'bad'; message: string; adminOk?: boolean };
type ConnectionMode = 'direct' | 'proxy' | 'v2ray' | 'mikrotik';
type ConnectionApi = {
  ok: boolean;
  mode: ConnectionMode;
  revision?: string;
  proxy: { scheme: string; host: string; port: string; username: string; password_configured: boolean };
  v2ray: { uri_configured: boolean; uri_preview: string; protocol: string; xray_available: boolean };
  mikrotik: { host: string; port: string; username: string; password_configured: boolean };
  last_test: { status: string; message: string; at: string; latency_ms: string };
};
type TestAccountTarget = { server_id: number; inbound_ids: number[] };
type TestAccountApi = { ok: boolean; settings: Record<string, string>; targets?: TestAccountTarget[]; usage_count: number; usage_items?: { id: number; telegram_id: number; created_at?: string; service_id?: number | null; user?: UserItem | null }[]; servers: ServerItem[] };
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
  step?: string | number;
  min?: string | number;
  showWhen?: { name: string; value?: string; values?: string[] };
  showWhenAll?: { name: string; value?: string; values?: string[] }[];
  hidden?: boolean;
};

const navGroups: { label: string; items: { key: SectionKey; title: string; href: string; icon: any }[] }[] = [
  { label: 'Main', items: [{ key: 'dashboard', title: 'Dashboard', href: '/admin', icon: LayoutDashboard }] },
  {
    label: 'Sales',
    items: [
      // Match the Telegram purchase journey: service type → category → plan → payment.
      { key: 'service-types', title: 'Service Types', href: '/admin/service-types', icon: Gift },
      { key: 'categories', title: 'Categories', href: '/admin/categories', icon: Layers3 },
      { key: 'plans', title: 'Plans', href: '/admin/plans', icon: Package },
      { key: 'payments', title: 'Payments', href: '/admin/payments', icon: CreditCard },
      { key: 'discounts', title: 'Discount Codes', href: '/admin/discounts', icon: Tag },
      { key: 'test-account', title: 'Test Account', href: '/admin/test-account', icon: ShieldCheck },
      { key: 'openvpn-profiles', title: 'Profile OpenVPN', href: '/admin/openvpn-profiles', icon: FileText },
      { key: 'pasarguard-panel-sales', title: 'PasarGuard Panel Sales', href: '/admin/pasarguard-panel-sales', icon: Wallet }
    ]
  },
  { label: 'Users', items: [{ key: 'users', title: 'Users', href: '/admin/users', icon: Users }, { key: 'resellers', title: 'Resellers', href: '/admin/resellers', icon: UserCog }] },
  { label: 'System', items: [{ key: 'servers', title: 'Servers', href: '/admin/servers', icon: Server }, { key: 'connection', title: 'Connection', href: '/admin/connection', icon: Wifi }, { key: 'backup', title: 'Backup & Restore', href: '/admin/backup', icon: Archive }, { key: 'custom', title: 'Custom', href: '/admin/custom', icon: Bot }, { key: 'settings', title: 'Settings', href: '/admin/settings', icon: Settings }] }
];

function publicWebPath(path: string): string {
  if (typeof window === 'undefined') return path;
  const current = window.location.pathname || '';
  const adminIndex = current.indexOf('/admin');
  const loginIndex = current.indexOf('/login');
  const setupIndex = current.indexOf('/setup');
  const logoutIndex = current.indexOf('/logout');
  const indexes = [adminIndex, loginIndex, setupIndex, logoutIndex].filter((x) => x >= 0);
  const prefix = indexes.length ? current.slice(0, Math.min(...indexes)) : '';
  return `${prefix}${path.startsWith('/') ? path : `/${path}`}`;
}

function internalAdminPath(pathname: string): string {
  const index = pathname.indexOf('/admin');
  return index >= 0 ? pathname.slice(index) : pathname;
}

const sectionTitles: Record<SectionKey, { title: string; subtitle: string }> = {
  dashboard: { title: 'Dashboard 👋', subtitle: '' },
  'service-types': { title: 'Service Types', subtitle: 'Create and manage the service categories visible inside the bot.' },
  'test-account': { title: 'Test Account', subtitle: 'Configure the trial account users can receive from the Telegram bot.' },
  'openvpn-profiles': { title: 'Profile OpenVPN', subtitle: 'Upload, edit, view and bind .ovpn server profiles for MikroTik / Custom plans.' },
  'pasarguard-panel-sales': { title: 'PasarGuard Panel Sales', subtitle: 'Initial sale price, PAYG wallet tariffs, user limits, server, and reseller panel orders.' },
  plans: { title: 'Plans', subtitle: 'Public plans and reseller packages with real server bindings.' },
  payments: { title: 'Payments', subtitle: 'Card-to-card and account destinations for public and reseller payments.' },
  discounts: { title: 'Discount Codes', subtitle: 'Percentage and fixed Toman discount codes with per-user limits.' },
  users: { title: 'Users', subtitle: 'Search all Telegram users, wallets, reseller access, referrals and purchases.' },
  resellers: { title: 'Resellers', subtitle: 'Manage reseller capacity, used traffic, and expiry dates.' },
  servers: { title: 'Servers', subtitle: 'Sanaei / 3x-ui servers and dedicated MikroTik / Custom router connections.' },
  categories: { title: 'Categories', subtitle: 'Group servers and plans for a clean purchase flow.' },
  connection: { title: 'Connection', subtitle: 'Route Telegram traffic through direct, proxy, MikroTik SOCKS, or V2/Xray connections.' },
  backup: { title: 'Backup & Restore', subtitle: 'Configure website and bot backups, test Telegram delivery, and restore local backup files safely.' },
  custom: { title: 'Custom', subtitle: 'View, search, edit and reset every detected Telegram bot message, prompt, caption and button label.' },
  settings: { title: 'Settings', subtitle: 'Website access, installation tools and reset controls.' }
};

function statusClass(status?: string) {
  const s = String(status || '').toLowerCase();
  if (['paid', 'approved', 'completed', 'active', 'success'].some((x) => s.includes(x))) return 'green';
  if (['pending', 'waiting'].some((x) => s.includes(x))) return 'yellow';
  if (['failed', 'rejected', 'deleted', 'inactive', 'blocked'].some((x) => s.includes(x))) return 'red';
  return 'purple';
}

function planPriceDisplay(plan: PlanItem) {
  if (String(plan.pricing_currency || 'IRT').toUpperCase() === 'USD') {
    const raw = Number(plan.price_usd || 0);
    return `$${Number.isFinite(raw) ? raw.toLocaleString('en-US', { maximumFractionDigits: 4 }) : '0'}`;
  }
  return toman(plan.price_irt);
}

function firstLetter(value?: string | number | null) {
  return String(value || 'A').trim().charAt(0).toUpperCase() || 'A';
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
  const [sidebarHovered, setSidebarHovered] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const collapsed = !mobileOpen && !sidebarHovered;
  const [globalQuery, setGlobalQuery] = useState('');
  const [modal, setModal] = useState<ModalForm | null>(null);
  const [profileOpen, setProfileOpen] = useState(false);
  const [profileAvatar, setProfileAvatar] = useState<string>('');
  const [reloadKey, setReloadKey] = useState(0);
  const [authRequired, setAuthRequired] = useState(false);
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
    if (typeof window !== 'undefined') {
      const target = publicWebPath(item.href);
      if (window.location.pathname !== target) window.history.pushState({}, '', target);
    }
  }

  useEffect(() => {
    const onPop = () => {
      const current = internalAdminPath(window.location.pathname);
      const match = navGroups.flatMap((g) => g.items).find((x) => x.href === current);
      if (match) setSection(match.key);
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  async function submitModal(values: Record<string, FormDataEntryValue>) {
    if (!modal) return;
    try {
      const result: any = await submitForm(modal.action, values.badge_color ? { ...values, badge_emoji: circleEmojiForColor(String(values.badge_color)) } : values);
      if (result?.logout) {
        show(result?.message || 'Website login changed. Please login again.', true);
        window.setTimeout(() => { window.location.href = result?.redirect || publicWebPath('/login?updated=1'); }, 650);
        return;
      }
      if (result?.path_changed && result?.redirect) {
        show(result?.message || 'Web path changed successfully.', true);
        window.setTimeout(() => { window.location.href = result.redirect; }, 550);
        return;
      }
      show(result?.message || 'Saved successfully', true);
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
          <a className="btn primary mt-4" href={publicWebPath('/login')}>Open Login</a>
        </section>
        {toast && <div className={`toast ${toast.good ? 'good' : 'bad'}`}>{toast.text}</div>}
      </main>
    );
  }

  return (
    <div className={`shell section-${section}`}>
      <div className="admin-ambient" aria-hidden="true">
        <span className="admin-ambient-glow" />
        <span className="admin-ambient-wave one" />
        <span className="admin-ambient-wave two" />
      </div>
      <aside
        className={`sidebar ${collapsed ? 'collapsed' : ''} ${mobileOpen ? 'mobile-open' : ''}`}
        onMouseEnter={() => setSidebarHovered(true)}
        onMouseLeave={() => setSidebarHovered(false)}
        onFocusCapture={() => setSidebarHovered(true)}
        onBlurCapture={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setSidebarHovered(false);
        }}
      >
        <div className="sidebar-head">
          <a className="brand" href={publicWebPath('/admin')} onClick={(event) => openSection({ key: 'dashboard', href: '/admin' }, event)}>
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
                  <a key={item.key} className={`nav-link ${section === item.key ? 'active' : ''}`} title={item.title} aria-label={item.title} href={item.href} onClick={(event) => openSection(item, event)}>
                    <Icon /> <span className="nav-title">{item.title}</span>
                  </a>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="sidebar-language-row" title="Language">
            <Languages size={19} aria-hidden="true" />
            <span className="sidebar-language-label">Language</span>
            <LanguageSwitch compact />
          </div>
          <a
            className="sidebar-github"
            href="https://github.com/officialdarvish/D_bot"
            target="_blank"
            rel="noopener noreferrer"
            title="D Bot on GitHub"
            aria-label="D Bot on GitHub"
          >
            <Github size={20} aria-hidden="true" />
            <span>GitHub Project</span>
          </a>
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
              {section !== 'dashboard' && <button className="btn" onClick={() => setReloadKey((x) => x + 1)}><RefreshCw size={16} /> Refresh</button>}
            </div>
          </div>

          <SectionRenderer section={section} query={globalQuery} reloadKey={reloadKey} setAuthRequired={setAuthRequired} openModal={setModal} runAction={runAction} show={show} />
        </div>
      </main>
      {modal && <FormModal modal={modal} onClose={() => setModal(null)} onSubmit={submitModal} show={show} />}
      {profileOpen && <ProfileModal avatar={profileAvatar} setAvatar={setProfileAvatar} onClose={() => setProfileOpen(false)} show={show} />}
      {toast && <div className={`toast ${toast.good ? 'good' : 'bad'}`}>{toast.text}</div>}
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
        <a className="btn danger" href={publicWebPath('/logout')}><LogOut size={16} /> Logout</a>
      </motion.div>
    </div>
  );
}

function SectionRenderer(props: { section: SectionKey; query: string; reloadKey: number; setAuthRequired: (v: boolean) => void; openModal: (form: ModalForm) => void; runAction: (path: string, message?: string) => void; show: (message: string, good?: boolean) => void }) {
  switch (props.section) {
    case 'dashboard': return <DashboardSection {...props} />;
    case 'users': return <UsersSection {...props} />;
    case 'servers': return <ServersSection {...props} />;
    case 'categories': return <CategoriesSection {...props} />;
    case 'connection': return <ConnectionSection {...props} />;
    case 'plans': return <PlansSection {...props} />;
    case 'payments': return <PaymentsSection {...props} />;
    case 'discounts': return <DiscountsSection {...props} />;
    case 'resellers': return <ResellersSection {...props} />;
    case 'custom': return <CustomSection reloadKey={props.reloadKey} setAuthRequired={props.setAuthRequired} show={props.show} />;
    case 'settings': return <SettingsSection {...props} />;
    case 'backup': return <BackupSection {...props} />;
    case 'service-types': return <ServiceTypesSection {...props} />;
    case 'test-account': return <TestAccountSection {...props} />;
    case 'openvpn-profiles': return <OpenVPNProfilesSection {...props} />;
    case 'pasarguard-panel-sales': return <PasarGuardPanelSalesSection {...props} />;
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

function DashboardSection({ reloadKey, setAuthRequired, show }: any) {
  const [resetting, setResetting] = useState(false);
  const [refreshCycle, setRefreshCycle] = useState(0);
  const { data, loading, error } = useApi<DashboardApi>('/admin/api/v2/dashboard', reloadKey + refreshCycle, setAuthRequired);
  useEffect(() => {
    const interval = window.setInterval(() => setRefreshCycle((v) => v + 1), 60_000);
    return () => window.clearInterval(interval);
  }, []);
  const rawChartData = data?.chart_ranges?.[0]?.data || [];
  const chartData = rawChartData;
  const chartTicks = chartData.filter((_, index) => index % 3 === 0).map((row) => row.label);
  const stats = data?.stats || {};
  if (loading) return <SkeletonGrid />;
  if (error || !data) return <EmptyState message={error || 'Dashboard could not be loaded.'} />;
  const displaySales = Number(stats.monthly_sales || 0);
  const displayTrend = Number(stats.monthly_sales_change || 0);
  const statCards = [
    { label: 'Total Revenue', value: toman(displaySales), trend: displayTrend, icon: Gauge, cls: 'purple' },
    { label: 'New Orders', value: money(stats.today_orders), trend: stats.orders_change, icon: ShoppingCart, cls: 'blue' },
    { label: 'Total Users', value: money(stats.users_total), trend: stats.users_change, icon: Users, cls: 'green' },
    { label: 'Active Services', value: money(stats.active_services), trend: stats.conversion_rate, icon: Server, cls: 'cyan' }
  ];
  return (
    <>
      <div className="cards4">
        {statCards.map((card, index) => <StatCard key={card.label} {...card} index={index} />)}
      </div>
      <div className="dashboard-grid dashboard-grid-clean">
        <section className="panel revenue-panel">
          <div className="panel-head">
            <div><h2>Revenue Overview</h2></div>
            <div className="actions">
              <button className="btn" type="button" disabled={resetting} onClick={async () => { if (!window.confirm('Start a new permanent 30-day display period? Previous sales remain in Export.')) return; setResetting(true); try { await submitForm('/admin/api/v2/dashboard/revenue-reset', {}); setRefreshCycle((v) => v + 1); show?.('A new 30-day period has started. Previous sales remain in Export.', true); } catch (error) { show?.(String(error), false); } finally { setResetting(false); } }}><RefreshCw size={15} /> {resetting ? 'Resetting...' : 'Reset Display'}</button>
            </div>
          </div>
          <div className="panel-title-value"><strong>{toman(displaySales)}</strong><span className="stat-trend">{pct(displayTrend)} vs previous range</span></div>
          <div className="chart-wrap">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
                <defs><linearGradient id="rev" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#69a7ff" stopOpacity={0.65}/><stop offset="95%" stopColor="#69a7ff" stopOpacity={0}/></linearGradient></defs>
                <CartesianGrid stroke="rgba(148,163,184,.12)" vertical={false} />
                <XAxis dataKey="label" ticks={chartTicks} interval={0} minTickGap={8} tick={{ fill: '#aab4c8', fontSize: 12 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: '#aab4c8', fontSize: 12 }} axisLine={false} tickLine={false} tickFormatter={(v) => tomanChart(Number(v))} />
                <Tooltip contentStyle={{ background: '#091524', border: '1px solid rgba(145,190,253,.22)', borderRadius: 12 }} formatter={(value) => `${tomanChart(Number(value))} × 1,000 Toman`} />
                <Area type="monotone" dataKey="sales" stroke="#7db3ff" strokeWidth={3} fill="url(#rev)" dot={false} activeDot={{ r: 7 }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </section>
        <SystemStatus resources={data.resources} />
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
  return <section className="panel system-status-wide"><div className="panel-head"><div><h2>System Status</h2><p className="muted system-status-subtitle">Live resource usage</p></div><span className="badge green">Live</span></div><div className="progress-list system-status-list">{rows.map((r) => <div className={`progress-row ${r.cls}`} key={r.title}><div className="progress-name"><span className="progress-icon">{r.icon}</span><span>{(/ram/i.test(r.title) ? 'RAM Usage' : /ssd|disk/i.test(r.title) ? 'Disk Usage' : /cpu/i.test(r.title) ? 'CPU Usage' : r.title)}</span></div><div className="progress-value-row"><div className="progress-track"><div className="progress-fill" style={{ width: `${Math.min(100, Math.max(0, Number(r.percent || 0)))}%` }} /></div><strong>{Math.round(Number(r.percent || 0))}%</strong></div></div>)}</div></section>;
}

function RecentOrders({ orders }: { orders: OrderItem[] }) {
  return <section className="card table-card"><div className="panel-head"><h2>Recent Orders</h2></div><div className="table-scroll"><table><thead><tr><th>Order ID</th><th>User</th><th>Plan</th><th>Amount</th><th>Payment</th><th>Status</th><th>Date</th></tr></thead><tbody>{orders.map((o) => <tr key={o.id}><td className="text-violet-300">#ORD-{o.id}</td><td><div className="row-left"><span className="tiny-avatar">{firstLetter(o.user?.full_name || o.user?.username)}</span>{o.user?.full_name || o.user?.username || o.user?.telegram_id || '-'}</div></td><td>{orderPlanTitle(o)}</td><td>{toman(o.amount_irt)}</td><td>{paymentLabel(o.payment_method)}</td><td><span className={`badge ${statusClass(o.status)}`}>{o.status}</span></td><td>{shortDate(o.created_at)}</td></tr>)}</tbody></table></div></section>;
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


type PasarGuardSaleApi = {
  ok: boolean;
  settings: Record<'enabled' | 'server_id' | 'price_irt' | 'gb_price_irt' | 'hourly_price_irt' | 'max_users', string>;
  servers: { id: number; name: string }[];
  orders: { id: number; username: string; telegram_id: number; status: string; price_irt: number; traffic_bytes: number; charged_irt: number; suspended: boolean; last_error?: string | null }[];
};

function PasarGuardPanelSalesSection({ reloadKey, setAuthRequired, show }: any) {
  const api = useApi<PasarGuardSaleApi>('/admin/api/v2/pasarguard-panel-sales', reloadKey, setAuthRequired);
  const [config, setConfig] = useState<PasarGuardSaleApi['settings']>({
    enabled: '0', server_id: '0', price_irt: '0', gb_price_irt: '0', hourly_price_irt: '0', max_users: '0'
  });
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (api.data?.settings) setConfig(api.data.settings); }, [api.data]);
  const update = (name: keyof PasarGuardSaleApi['settings'], value: string) => setConfig((prev) => ({...prev, [name]: value}));
  async function save() {
    const data = api.data;
    if (!data) return;
    if (['price_irt','gb_price_irt','hourly_price_irt','max_users'].some((key) => !/^\d+$/.test(config[key as keyof PasarGuardSaleApi['settings']]))) {
      show('Prices and user limits must be non-negative integers', false); return;
    }
    if (config.enabled === '1' && !data.servers.some((server) => server.id === Number(config.server_id))) {
      show('Select an active PasarGuard server', false); return;
    }
    setSaving(true);
    try {
      await submitForm('/admin/pasarguard-panel-sales/save', config);
      show('PasarGuard PAYG settings saved and synchronized with Telegram', true);
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      if (msg === 'AUTH_REQUIRED') setAuthRequired(true);
      show(msg, false);
    } finally { setSaving(false); }
  }
  if (api.loading) return <SkeletonGrid />;
  if (api.error || !api.data) return <EmptyState message={api.error || 'Panel sale settings unavailable'} />;
  const data = api.data;
  return <div className="pg-panel-sale-page">
    <section className="panel pg-panel-sale-settings">
      <h2>PasarGuard Reseller Panel Sales</h2>
      <p className="muted">This feature is independent from D Bot's existing Request Reseller menu. Changes are saved to the same settings used by Telegram Admin.</p>
      <div className="pg-form-grid">
        <label><span>Sales status</span><select value={config.enabled} onChange={(e) => update('enabled', e.target.value)}><option value="0">Disabled</option><option value="1">Enabled</option></select></label>
        <label><span>PasarGuard server</span><select value={config.server_id} onChange={(e) => update('server_id', e.target.value)}><option value="0">Select a PasarGuard server</option>{data.servers.map((server) => <option key={server.id} value={server.id}>{server.name}</option>)}</select></label>
        <label><span>Initial purchase (Toman) — 0 = Free</span><input type="number" min="0" step="1" value={config.price_irt} onChange={(e) => update('price_irt', e.target.value)} /></label>
        <label><span>PAYG price per GB (Toman)</span><input type="number" min="0" step="1" value={config.gb_price_irt} onChange={(e) => update('gb_price_irt', e.target.value)} /></label>
        <label><span>Reseller rental per hour (Toman)</span><input type="number" min="0" step="1" value={config.hourly_price_irt} onChange={(e) => update('hourly_price_irt', e.target.value)} /></label>
        <label><span>Maximum users — 0 = Unlimited</span><input type="number" min="0" step="1" value={config.max_users} onChange={(e) => update('max_users', e.target.value)} /></label>
      </div>
      <p className="muted">Charges are deducted from the Telegram user's main wallet each minute based on recorded traffic and elapsed active time. Once the wallet reaches zero, the panel's users are disabled remotely until the owner tops up and resumes. The previous tariff is retained for already purchased panels.</p>
      <button type="button" className="btn primary" disabled={saving} onClick={save}><Save size={16} /> {saving ? 'Saving...' : 'Save and sync with Telegram'}</button>
    </section>
    <section className="panel">
      <h2>Purchased panels and billing</h2>
      <div className="table-scroll"><table><thead><tr><th>Order</th><th>Username</th><th>Telegram ID</th><th>Purchase</th><th>Traffic (GB)</th><th>Debited</th><th>State</th></tr></thead><tbody>
        {data.orders.map((order) => <tr key={order.id}><td>#{order.id}</td><td>{order.username}</td><td>{order.telegram_id}</td><td>{toman(order.price_irt)}</td><td>{(order.traffic_bytes / 1073741824).toFixed(3)}</td><td>{toman(order.charged_irt)}</td><td>{order.suspended ? 'Suspended' : order.status}{order.last_error ? <div className="muted">{order.last_error}</div> : null}</td></tr>)}
        {!data.orders.length && <tr><td colSpan={7}>No panel orders yet</td></tr>}
      </tbody></table></div>
    </section>
  </div>;
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
      const isPasarGuard = s.server_type === 'pasarguard';
      const serviceBadgeEmoji = s.badge_emoji || (isCustom ? '🟠' : (isPasarGuard ? '🟢' : '🔵'));
      const serviceBadgeLabel = s.badge_label || (isCustom ? 'MikroTik / OpenVPN' : (isPasarGuard ? 'PasarGuard' : 'V2Ray'));
      const serviceBadgeColor = s.badge_color || (isCustom ? '#f97316' : (isPasarGuard ? '#22c55e' : '#2563eb'));
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
        [isPasarGuard ? 'Groups' : 'Inbounds', s.inbound_ids?.length || 0],
        ...(isPasarGuard ? [
          ['PasarGuard role', `${s.pasarguard_role_name || 'custom'}${s.pasarguard_restricted ? ' · Restricted' : ''}`],
          ['User scope', String(s.pasarguard_capabilities?.users_read_scope || (s.pasarguard_restricted ? 'own' : 'all')).toUpperCase()],
          ['Group source', s.pasarguard_group_source || 'api'],
          ...(s.pasarguard_require_template ? [['Template routing', 'Auto-detected'] as [string, any]] : []),
        ] as [string, any][] : []),
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
  const groupApi = useApi<ServerGroupsApi>('/admin/api/v2/server-groups', reloadKey, setAuthRequired);
  const [publicOrder, setPublicOrder] = useState<PlanItem[]>([]);
  const [resellerOrder, setResellerOrder] = useState<ResellerPackage[]>([]);
  const [dragging, setDragging] = useState<{ kind: 'public' | 'reseller'; id: number } | null>(null);
  const [savingOrder, setSavingOrder] = useState('');

  useEffect(() => {
    if (!plans.data) return;
    setPublicOrder(plans.data.plans || []);
    setResellerOrder(plans.data.reseller_packages || []);
  }, [plans.data]);

  if (plans.loading || cats.loading || srvs.loading || groupApi.loading) return <SkeletonGrid />;
  if (plans.error || !plans.data) return <EmptyState message={plans.error || 'Plans could not be loaded.'} />;
  const catOpts = categoryOptions(cats.data?.items || []);
  const groupsByServer = new Map((groupApi.data?.items || []).map((row) => [Number(row.server_id), row.groups || []]));
  const serverItems = (srvs.data?.items || []).map((server) => ({ ...server, client_groups: groupsByServer.get(Number(server.id)) || [] }));
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
          {publicPlans.map((p) => <div key={`p${p.id}`} className={`drag-card ${dragging?.id === p.id && dragging.kind === 'public' ? 'dragging' : ''}`} draggable onDragStart={() => setDragging({ kind: 'public', id: p.id })} onDragOver={(e) => e.preventDefault()} onDrop={() => onDropPlan('public', p.id)} onDragEnd={() => setDragging(null)}><EntityCard headingLevel={3} title={p.title} icon={<Package />} badge={p.is_active ? 'Public / Active' : 'Public / Inactive'} badgeClass={p.is_active ? 'green' : 'red'} kvs={[["Price", planPriceDisplay(p)], ['Volume', `${p.volume_gb} GB`], ['Duration', `${p.duration_days} days`], ['Server', p.server_id || '-'], ['Category', p.category_id || '-'], ['Inbound mode', p.inbound_mode === 'manual' ? 'Manual' : 'Automatic'], ['Inbounds', p.inbound_mode === 'manual' ? (p.inbound_ids?.length || 0) : 'All active'], ['Client group', p.group_name || 'None'], ['HWID devices', Number(p.hwid_limit || 0) > 0 ? `${p.hwid_limit} max` : 'Unlimited']]} actions={<><span className="drag-handle"><ListChecks size={15} /> Drag</span><button className="btn" onClick={() => openModal(planForm(catOpts, serverItems, p))}>Edit</button><button className={p.is_active ? 'btn danger' : 'btn success'} onClick={() => runAction(`/admin/toggle/plans/${p.id}`, p.is_active ? 'Plan deactivated' : 'Plan activated')}>{p.is_active ? 'Deactivate' : 'Activate'}</button><button className="btn danger" onClick={() => runAction(`/admin/plans/${p.id}/delete`, 'Plan deleted')}>Delete</button></>} /></div>)}
        </div>
      </section>
      <section className="plan-order-panel">
        <div className="panel-head"><h2>Reseller Plans Order</h2><span className="badge purple">Reseller Menu</span></div>
        <div className="section-grid plan-sort-grid">
          {resellerPlans.map((p) => <div key={`r${p.id}`} className={`drag-card ${dragging?.id === p.id && dragging.kind === 'reseller' ? 'dragging' : ''}`} draggable onDragStart={() => setDragging({ kind: 'reseller', id: p.id })} onDragOver={(e) => e.preventDefault()} onDrop={() => onDropPlan('reseller', p.id)} onDragEnd={() => setDragging(null)}><EntityCard headingLevel={3} title={p.title} icon={<ShieldCheck />} badge={p.is_active ? 'Reseller / Active' : 'Reseller / Inactive'} badgeClass={p.is_active ? 'purple' : 'red'} kvs={[["Price", p.pricing_currency === 'USD' ? `$${p.price_usd || '0'}` : toman(p.price_irt)], ['Volume', `${p.volume_gb} GB`], ['Validity', `${p.reseller_validity_days} days`], ['Server', p.server_id || '-']]} actions={<><span className="drag-handle"><ListChecks size={15} /> Drag</span><button className="btn" onClick={() => openModal(resellerPlanForm(srvOpts, p))}>Edit</button><button className={p.is_active ? 'btn danger' : 'btn success'} onClick={() => runAction(`/admin/toggle/reseller-plans/${p.id}`, p.is_active ? 'Reseller plan deactivated' : 'Reseller plan activated')}>{p.is_active ? 'Deactivate' : 'Activate'}</button><button className="btn danger" onClick={() => runAction(`/admin/plans/reseller/${p.id}/delete`, 'Reseller plan deleted')}>Delete</button></>} /></div>)}
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
  const publicPaymentServers = (srvs.data?.items || []).filter((server) => server.scope === 'public' || server.scope === 'all');
  const srvOpts = serverOptions(publicPaymentServers);
  const rows = filterItems(payments.data.items, query, ['owner_name', 'card_number', 'server_type']);
  return <><div className="filterbar"><button className="btn primary" onClick={() => openModal(paymentForm(srvOpts))}><Plus size={16} /> Add Payment</button><span className="badge">{rows.length} accounts</span></div><div className="section-grid">{rows.map((p) => <EntityCard key={p.id} title={p.owner_name} icon={<CreditCard />} badge={p.server_type === 'reseller' ? 'Reseller' : 'Public'} badgeClass={p.is_active ? 'green' : 'red'} kvs={[["Card / Account", p.card_number], ['Server Type', p.server_type], ['Server ID', p.server_id || '-'], ['Receipt reviewer', p.reviewer_telegram_id || 'Main admins']]} actions={<><button className="btn" onClick={() => openModal(paymentForm(srvOpts, p))}>Edit</button><button className="btn danger" onClick={() => runAction(`/admin/payments/${p.id}/delete`, 'Payment account deleted')}>Delete</button></>} />)}</div></>;
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
  const servers = useApi<ApiList<ServerItem>>('/admin/api/v2/servers', reloadKey, setAuthRequired);
  const groupApi = useApi<ServerGroupsApi>('/admin/api/v2/server-groups', reloadKey, setAuthRequired);
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
  if (loading || servers.loading || groupApi.loading) return <SkeletonGrid />;
  if (error || servers.error || !data) return <EmptyState message={error || servers.error || 'Resellers could not be loaded.'} />;
  const groupsByServer = new Map((groupApi.data?.items || []).map((row) => [Number(row.server_id), row.groups || []]));
  const serverItems = (servers.data?.items || []).map((server) => ({ ...server, client_groups: groupsByServer.get(Number(server.id)) || [] }));
  const rows = filterItems(data.items, query, ['user.full_name', 'user.username', 'user.telegram_id']);
  if (selected) return <ResellerServicesLetter reseller={selected} reloadKey={reloadKey} setAuthRequired={setAuthRequired} onClose={() => setSelected(null)} />;
  return <>
    <div className="filterbar"><button className="btn primary" onClick={() => openModal(resellerForm(undefined, serverItems))}><Plus size={16} /> Add Reseller</button><span className="badge">{rows.length} resellers</span></div>
    <div className="section-grid">{rows.map((r) => { const remain = Number(r.remaining_bytes ?? Number(r.total_bytes || 0)); return <EntityCard key={r.id} title={r.user.full_name || r.user.username || String(r.user.telegram_id)} icon={<UserCog />} badge={r.is_active ? 'Active' : 'Inactive'} badgeClass={r.is_active ? 'green' : 'red'} kvs={[["Telegram ID", r.user.telegram_id], ['Total', gbFromBytes(r.total_bytes)], ['Used', gbFromBytes(r.used_bytes)], ['Reserved', gbFromBytes(r.reserved_bytes)], ['Remaining', gbFromBytes(remain)], ['Inbound mode', r.inbound_mode === 'manual' ? `Manual (${r.inbound_ids?.length || 0})` : 'Automatic (all active)'], ['Client group', r.group_name || 'No client group'], ['Expires', shortDate(r.expires_at)]]} actions={<><button className="btn success" disabled={refreshingId === r.id} onClick={() => refreshReseller(r.id)}><RefreshCw size={15} className={refreshingId === r.id ? 'spin' : ''} /> {refreshingId === r.id ? 'Refreshing' : 'Refresh Stats'}</button><button className="btn" onClick={() => setSelected(r)}><FileText size={15} /> List</button><button className="btn" onClick={() => openModal(resellerForm(r, serverItems))}>Edit</button><button className="btn danger" onClick={() => runAction(`/admin/resellers/${r.id}/delete`, 'Reseller deleted')}>Delete</button></>} />; })}</div>
  </>;
}

function ResellerServicesLetter({ reseller, reloadKey, setAuthRequired, onClose }: { reseller: ResellerItem; reloadKey: number; setAuthRequired: (v: boolean) => void; onClose: () => void }) {
  const { data, loading, error } = useApi<ResellerServicesApi>(`/admin/api/v2/resellers/${reseller.id}/services`, reloadKey, setAuthRequired);
  const items = data?.items || [];
  const activities = data?.activities || [];
  const account = data?.reseller || reseller;
  const activeCount = items.filter((x) => x.is_active).length;
  const renewCount = activities.filter((x) => x.action === 'renew').length;
  const createCount = activities.filter((x) => x.action === 'create').length;
  const topupCount = activities.filter((x) => x.action === 'topup' || x.action === 'quota_adjustment').length;
  const failedCount = activities.filter((x) => x.status === 'failed' || x.action.endsWith('_failed')).length;
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
      <div><b>{createCount}</b><span>Created orders</span></div>
      <div><b>{renewCount}</b><span>Renewal orders</span></div>
      <div><b>{topupCount}</b><span>Quota recharges</span></div>
      <div><b>{failedCount}</b><span>Failed operations</span></div>
    </div>
    {loading ? <p className="muted">Loading reseller configs...</p> : error ? <EmptyState message={error} /> : <>
      <div className="reseller-activity-head">
        <div><h3>Activity & renewal history</h3><p className="muted">Quota recharges, purchases, renewals, quota deductions and panel errors are recorded with before/after accounting details.</p></div>
        <span className="badge">{activities.length} operations</span>
      </div>
      <div className="reseller-activity-list">
        {activities.length ? activities.map((activity) => {
          const isFailed = activity.status === 'failed' || activity.action.endsWith('_failed');
          const isRenew = activity.action === 'renew' || activity.action === 'renew_failed';
          const isTopup = activity.action === 'topup';
          const isAdjustment = activity.action === 'quota_adjustment';
          const isAddVolume = activity.action === 'add_volume' || activity.action === 'add_volume_failed';
          const isAddDays = activity.action === 'add_days' || activity.action === 'add_days_failed';
          const actionClass = isFailed ? 'failed' : isRenew ? 'renew' : isTopup ? 'topup' : isAdjustment ? 'adjust' : (isAddVolume || isAddDays) ? 'volume' : 'create';
          const badgeClass = isFailed ? 'red' : isRenew ? 'yellow' : (isTopup || isAdjustment) ? 'blue' : 'green';
          const label = activity.action_label || activity.action.replaceAll('_', ' ');
          const quotaKnown = !activity.legacy_quota_snapshot_unavailable && (activity.source !== 'backfill' || Number(activity.quota_before_bytes || 0) !== 0 || Number(activity.quota_after_bytes || 0) !== 0 || Number(activity.quota_remaining_after_bytes || 0) !== 0);
          const netDelta = Number(activity.quota_delta_bytes || 0);
          const isCreateOrRenew = activity.action === 'create' || activity.action === 'renew';
          const hasExactOperationSnapshot = Number(activity.quota_snapshot_version || 0) >= 2;
          const displayQuotaSnapshot = isCreateOrRenew ? hasExactOperationSnapshot : quotaKnown;
          const quotaAfter = Math.max(0, Number(activity.quota_remaining_after_bytes ?? activity.quota_after_bytes ?? 0));
          const operationVolume = Math.max(0, Number(activity.requested_volume_bytes || activity.volume_bytes || activity.deducted_bytes || 0));
          const description = isFailed
            ? `${label} for ${activity.username}. The database quota was checked again after rollback.`
            : isTopup
              ? `Reseller quota was recharged${activity.package_title ? ` with ${activity.package_title}` : ''}.`
              : isAdjustment
                ? 'Reseller sellable quota was manually adjusted from the admin panel.'
                : isRenew
                  ? `User ${activity.username} was renewed and a new reseller quota cycle was settled.`
                  : isAddVolume
                    ? `Extra volume was added to ${activity.username}.`
                    : isAddDays
                      ? `Extra service days were added to ${activity.username}.`
                      : `User ${activity.username} was created and reseller quota was consumed.`;
          return <article className={`reseller-activity-order ${actionClass}`} key={activity.id}>
            <div className="activity-order-icon">{isFailed ? <XCircle size={19} /> : isRenew ? <RefreshCw size={19} /> : (isTopup || isAdjustment) ? <Wallet size={19} /> : <Plus size={19} />}</div>
            <div className="activity-order-main">
              <div className="activity-order-title">
                <b>{activity.username}</b>
                <span className={`badge ${badgeClass}`}>{label}</span>
              </div>
              <p>{description}</p>
              {isCreateOrRenew && hasExactOperationSnapshot && <div className="activity-quota-snapshot">
                <div>
                  <span>Service volume</span>
                  <b>{gbFromBytes(operationVolume)}{Number(activity.duration_days || 0) > 0 ? ` / ${Number(activity.duration_days)} days` : ''}</b>
                </div>
                <div>
                  <span>Reseller quota before</span>
                  <b>{gbFromBytes(activity.quota_before_bytes)}</b>
                </div>
                <div>
                  <span>Remaining after this operation</span>
                  <b>{gbFromBytes(quotaAfter)}</b>
                </div>
              </div>}
              {isCreateOrRenew && !hasExactOperationSnapshot && <div className="activity-quota-snapshot">
                <div><span>Service volume</span><b>{gbFromBytes(operationVolume)}{Number(activity.duration_days || 0) > 0 ? ` / ${Number(activity.duration_days)} days` : ''}</b></div>
                <div><span>Historical remaining quota</span><b>Not stored in older version</b></div>
                <div><span>Current reseller quota now</span><b>{gbFromBytes(accountRemaining)}</b></div>
              </div>}
              {isTopup && quotaKnown && <div className="activity-quota-snapshot">
                <div><span>Quota purchased</span><b>+{gbFromBytes(activity.added_bytes || activity.volume_bytes)}</b></div>
                <div><span>Reseller quota before</span><b>{gbFromBytes(activity.quota_before_bytes)}</b></div>
                <div><span>Remaining after this operation</span><b>{gbFromBytes(quotaAfter)}</b></div>
              </div>}
              {isAddVolume && quotaKnown && !isFailed && <div className="activity-quota-snapshot">
                <div><span>Volume added to service</span><b>+{gbFromBytes(activity.volume_bytes)}</b></div>
                <div><span>Reseller quota before</span><b>{gbFromBytes(activity.quota_before_bytes)}</b></div>
                <div><span>Remaining after this operation</span><b>{gbFromBytes(quotaAfter)}</b></div>
              </div>}
              {isAdjustment && quotaKnown && <div className="activity-quota-snapshot">
                <div><span>Quota change</span><b>{netDelta > 0 ? '+' : ''}{gbFromBytes(netDelta)}</b></div>
                <div><span>Reseller quota before</span><b>{gbFromBytes(activity.quota_before_bytes)}</b></div>
                <div><span>Remaining after this operation</span><b>{gbFromBytes(quotaAfter)}</b></div>
              </div>}
              {isAddDays && quotaKnown && !isFailed && <div className="activity-quota-snapshot">
                <div><span>Days added to service</span><b>+{Number(activity.duration_days || 0)} days</b></div>
                <div><span>Reseller quota before</span><b>{gbFromBytes(activity.quota_before_bytes)}</b></div>
                <div><span>Remaining after this operation</span><b>{gbFromBytes(quotaAfter)}</b></div>
              </div>}
              <div className="activity-order-meta">
                <span><strong>Activity:</strong> #RA-{activity.id}</span>
                {activity.service_id && <span><strong>Service:</strong> #{activity.service_id}</span>}
                {activity.request_id && <span><strong>Top-up request:</strong> #{activity.request_id}</span>}
                <span><strong>Volume:</strong> {gbFromBytes(activity.volume_bytes)}</span>
                {Number(activity.previous_volume_bytes || 0) > 0 && <span><strong>Previous service/quota:</strong> {gbFromBytes(activity.previous_volume_bytes)}</span>}
                {Number(activity.old_used_bytes || 0) > 0 && <span><strong>Old used:</strong> {gbFromBytes(activity.old_used_bytes)}</span>}
                {Number(activity.released_bytes || 0) > 0 && <span><strong>Returned from old cycle:</strong> +{gbFromBytes(activity.released_bytes)}</span>}
                {Number(activity.added_bytes || 0) > 0 && <span><strong>Added to reseller quota:</strong> +{gbFromBytes(activity.added_bytes)}</span>}
                {Number(activity.deducted_bytes || 0) > 0 && <span><strong>Deducted from reseller quota:</strong> -{gbFromBytes(activity.deducted_bytes)}</span>}
                {displayQuotaSnapshot && <span><strong>Quota before:</strong> {gbFromBytes(activity.quota_before_bytes)}</span>}
                {displayQuotaSnapshot && <span><strong>Remaining after operation:</strong> {gbFromBytes(quotaAfter)}</span>}
                {displayQuotaSnapshot && netDelta !== 0 && <span><strong>Net quota change:</strong> {netDelta > 0 ? '+' : ''}{gbFromBytes(netDelta)}</span>}
                {Number(activity.service_total_before_bytes || 0) > 0 && <span><strong>Service total before:</strong> {gbFromBytes(activity.service_total_before_bytes)}</span>}
                {Number(activity.service_total_after_bytes || 0) > 0 && <span><strong>Service total after:</strong> {gbFromBytes(activity.service_total_after_bytes)}</span>}
                {Number(activity.duration_days || 0) > 0 && <span><strong>Duration:</strong> {Number(activity.duration_days || 0)} days</span>}
                {activity.expires_at && <span><strong>Expires:</strong> {shortDate(activity.expires_at)}</span>}
                <span><strong>Server:</strong> {activity.server_name || '-'}</span>
                {activity.source && <span><strong>Source:</strong> {activity.source}</span>}
              </div>
              {activity.legacy_quota_snapshot_unavailable && <p className="activity-order-note">Legacy recharge: exact quota before/after was not stored in the old version.</p>}
              {isFailed && <div className="activity-order-error"><strong>{activity.error_type || 'Error'}:</strong> {activity.error_message || 'No error message was returned.'}</div>}
            </div>
            <time>{shortDate(activity.created_at)}</time>
          </article>;
        }) : <EmptyState message="No reseller activity has been recorded yet." />}
      </div>
      <div className="reseller-config-head"><h3>Current configs</h3><span className="badge">{items.length} users</span></div>
      <div className="table-scroll letter-table"><table><thead><tr><th>Username</th><th>Created</th><th>Used</th><th>Total</th><th>Remaining</th><th>Usage</th><th>Expires</th><th>Server</th><th>Status</th></tr></thead><tbody>{items.length ? items.map((svc) => <tr key={svc.id}><td><b>{svc.username}</b><div className="muted">#{svc.id}</div></td><td>{shortDate(svc.created_at)}</td><td>{gbFromBytes(svc.used_bytes)}</td><td>{gbFromBytes(svc.total_bytes)}</td><td>{gbFromBytes(svc.remaining_bytes)}</td><td><div className="usage-cell"><span>{Number(svc.used_percent || 0).toFixed(1)}%</span><div className="usage-track"><i style={{ width: `${Math.min(100, Math.max(0, Number(svc.used_percent || 0)))}%` }} /></div></div></td><td>{shortDate(svc.expires_at)}</td><td>{svc.server_name || '-'}</td><td><span className={`badge ${svc.is_active ? 'green' : 'red'}`}>{svc.is_active ? 'Active' : (svc.disabled_reason || 'Inactive')}</span></td></tr>) : <tr><td colSpan={9}><EmptyInline /></td></tr>}</tbody></table></div>
    </>}
  </section>;
}

function ConnectionSection({ reloadKey, setAuthRequired, show }: any) {
  const { data, loading, error, setData } = useApi<ConnectionApi>('/admin/api/v2/connection', reloadKey, setAuthRequired);
  const [mode, setMode] = useState<ConnectionMode>('direct');
  const [proxy, setProxy] = useState({ scheme: 'socks5', host: '', port: '1080', username: '', password: '' });
  const [v2Uri, setV2Uri] = useState('');
  const [mikrotik, setMikrotik] = useState({ host: '', port: '1080', username: '', password: '' });
  const [busy, setBusy] = useState<'test' | 'save' | ''>('');

  useEffect(() => {
    if (!data) return;
    setMode(data.mode || 'direct');
    setProxy((current) => ({
      ...current,
      scheme: data.proxy?.scheme || 'socks5',
      host: data.proxy?.host || '',
      port: String(data.proxy?.port || '1080'),
      username: data.proxy?.username || '',
      password: '',
    }));
    setMikrotik((current) => ({
      ...current,
      host: data.mikrotik?.host || '',
      port: String(data.mikrotik?.port || '1080'),
      username: data.mikrotik?.username || '',
      password: '',
    }));
    setV2Uri('');
  }, [data?.revision]);

  if (loading) return <SkeletonGrid />;
  if (error || !data) return <EmptyState message={error || 'Connection settings could not be loaded.'} />;

  const payload = () => ({
    mode,
    proxy_scheme: proxy.scheme,
    proxy_host: proxy.host,
    proxy_port: proxy.port,
    proxy_username: proxy.username,
    proxy_password: proxy.password,
    v2_uri: v2Uri,
    mikrotik_host: mikrotik.host,
    mikrotik_port: mikrotik.port,
    mikrotik_username: mikrotik.username,
    mikrotik_password: mikrotik.password,
  });

  async function refreshStatus() {
    try {
      const next = await fetchJson<ConnectionApi>('/admin/api/v2/connection');
      setData(next);
    } catch (err) {
      if ((err as Error)?.message === 'AUTH_REQUIRED') setAuthRequired(true);
    }
  }

  async function testConnection() {
    setBusy('test');
    try {
      const result: any = await submitForm('/admin/api/v2/connection/test', payload());
      show(result?.message || 'Telegram connection test passed.', true);
      await refreshStatus();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (message === 'AUTH_REQUIRED') setAuthRequired(true);
      else show(message || 'Telegram connection test failed.', false);
      await refreshStatus();
    } finally {
      setBusy('');
    }
  }

  async function saveConnection() {
    setBusy('save');
    try {
      const result: any = await submitForm('/admin/api/v2/connection/save', payload());
      show(result?.message || 'Connection settings saved. The Telegram bot is reloading automatically.', true);
      setProxy((current) => ({ ...current, password: '' }));
      setMikrotik((current) => ({ ...current, password: '' }));
      setV2Uri('');
      if (result?.ok) setData(result as ConnectionApi);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (message === 'AUTH_REQUIRED') setAuthRequired(true);
      else show(message || 'Connection settings could not be saved.', false);
    } finally {
      setBusy('');
    }
  }

  const lastStatus = String(data.last_test?.status || '').toLowerCase();
  const statusText = lastStatus === 'ok' ? 'Connected' : lastStatus === 'failed' ? 'Failed' : 'Not tested';
  const modeCards: { key: ConnectionMode; title: string; description: string; note: string; icon: any }[] = [
    { key: 'direct', title: 'Direct', description: 'Use the server network directly for Telegram.', note: 'No tunnel', icon: Globe2 },
    { key: 'proxy', title: 'Proxy', description: 'Connect through HTTP, SOCKS4 or SOCKS5.', note: 'HTTP / SOCKS', icon: Waypoints },
    { key: 'v2ray', title: 'V2 / Xray', description: 'Use a VLESS, VMess, Trojan or Shadowsocks share link.', note: 'Encrypted tunnel', icon: Network },
    { key: 'mikrotik', title: 'MikroTik SOCKS', description: 'Route Telegram through a MikroTik SOCKS5 gateway.', note: 'Router gateway', icon: Router },
  ];
  const selectedMode = modeCards.find((item) => item.key === mode) || modeCards[0];
  const activeMode = modeCards.find((item) => item.key === data.mode) || modeCards[0];
  const SelectedModeIcon = selectedMode.icon;
  const selectedEndpoint = mode === 'direct'
    ? 'Server network'
    : mode === 'proxy'
      ? (proxy.host ? `${proxy.host}:${proxy.port || '—'}` : 'Not configured')
      : mode === 'mikrotik'
        ? (mikrotik.host ? `${mikrotik.host}:${mikrotik.port || '—'}` : 'Not configured')
        : (data.v2ray?.uri_preview || (data.v2ray?.uri_configured ? 'Configured share link' : 'Not configured'));
  const selectedCredentials = mode === 'direct'
    ? 'Not required'
    : mode === 'v2ray'
      ? (data.v2ray?.uri_configured || v2Uri ? 'Encrypted share link' : 'Not configured')
      : mode === 'proxy'
        ? (proxy.username || data.proxy?.password_configured ? 'Configured' : 'Optional')
        : (mikrotik.username || data.mikrotik?.password_configured ? 'Configured' : 'Optional');

  return <div className="connection-page">
    <div className="connection-hero panel-card">
      <div className="connection-hero-copy">
        <span className="eyebrow"><Wifi size={15} /> Telegram Gateway</span>
        <h2>Telegram Connection</h2>
        <p>Choose how D Bot reaches Telegram when the bot server has restricted or filtered outbound access.</p>
        <div className="connection-stepper" aria-label="Connection setup steps">
          <span className="done"><b>1</b><i>Choose route</i></span>
          <span><b>2</b><i>Configure</i></span>
          <span><b>3</b><i>Test & Apply</i></span>
        </div>
      </div>
      <div className={`connection-health ${lastStatus === 'ok' ? 'good' : lastStatus === 'failed' ? 'bad' : ''}`}>
        <div className="connection-health-ring"><Activity size={19} /><span className="connection-health-dot" /></div>
        <div><small>Last test</small><strong>{statusText}</strong><em>{activeMode.title}</em></div>
        {data.last_test?.latency_ms ? <b>{data.last_test.latency_ms} ms</b> : <b>—</b>}
      </div>
    </div>

    <div className="connection-route-map panel-card" aria-label="Telegram route preview">
      <div className="connection-route-node">
        <span className="connection-route-icon"><Server size={21} /></span>
        <div><small>Traffic Source</small><strong>D Bot Server</strong><em>Application traffic</em></div>
      </div>
      <div className="connection-route-line"><span /><ArrowRight size={18} /></div>
      <div className="connection-route-node gateway active">
        <span className="connection-route-icon"><SelectedModeIcon size={21} /></span>
        <div><small>Selected gateway</small><strong>{selectedMode.title}</strong><em>{selectedMode.note}</em></div>
      </div>
      <div className="connection-route-line"><span /><ArrowRight size={18} /></div>
      <div className="connection-route-node telegram">
        <span className="connection-route-icon"><Send size={21} /></span>
        <div><small>Destination</small><strong>Telegram API</strong><em>Bot polling & messages</em></div>
      </div>
    </div>

    <div className="connection-section-head">
      <div><span className="connection-section-kicker">Step 1</span><h3>Choose connection method</h3><p>Select the route that should carry Telegram traffic.</p></div>
      <span className="connection-current-chip"><Zap size={14} /> Active: {activeMode.title}</span>
    </div>

    <div className="connection-mode-grid" role="radiogroup" aria-label="Connection Mode">
      {modeCards.map((item) => {
        const Icon = item.icon;
        const selected = mode === item.key;
        const active = data.mode === item.key;
        return <button
          key={item.key}
          type="button"
          role="radio"
          aria-checked={selected}
          className={`connection-mode-card ${selected ? 'active' : ''}`}
          onClick={() => setMode(item.key)}
        >
          <span className="connection-mode-top">
            <span className="connection-mode-icon"><Icon size={23} /></span>
            <span className="connection-mode-badges">{active ? <em>Active</em> : null}<span className="connection-mode-radio" /></span>
          </span>
          <strong>{item.title}</strong>
          <small>{item.description}</small>
          <span className="connection-mode-note">{item.note}</span>
        </button>;
      })}
    </div>

    <div className="connection-layout">
      <section className="panel-card connection-config-card">
        <div className="panel-headline connection-panel-headline">
          <div className="connection-panel-title"><span className="connection-panel-icon"><SelectedModeIcon size={20} /></span><div><span className="connection-section-kicker">Step 2</span><h3>Connection Settings</h3><p>Only the Telegram bot traffic is routed through this connection.</p></div></div>
          <span className="badge purple">{selectedMode.title}</span>
        </div>

        <div className="connection-scope-banner">
          <span className="connection-scope-icon"><ShieldCheck size={22} /></span>
          <div className="connection-scope-copy"><strong>Telegram-only route</strong><p>Bot polling, messages and Telegram API requests use this gateway. Other server traffic stays untouched.</p></div>
          <div className="connection-scope-pills"><span>Bot API</span><span>Polling</span><span>Messages</span></div>
        </div>

        <div className="connection-profile-card">
          <div className="connection-profile-main">
            <span className="connection-profile-icon"><SelectedModeIcon size={24} /></span>
            <div><small>Gateway profile</small><strong>{selectedMode.title}</strong><p>{selectedMode.description}</p></div>
          </div>
          <div className="connection-profile-facts">
            <div><span><Waypoints size={15} /></span><small>Route type</small><strong>{selectedMode.note}</strong></div>
            <div><span><Globe2 size={15} /></span><small>Endpoint</small><strong>{selectedEndpoint}</strong></div>
            <div><span><KeyRound size={15} /></span><small>Credentials</small><strong>{selectedCredentials}</strong></div>
          </div>
        </div>

        {mode === 'direct' && <div className="connection-empty-mode">
          <span className="connection-empty-visual"><Globe2 size={31} /></span>
          <div><strong>No gateway required</strong><p>D Bot will use the server&apos;s default internet connection.</p></div>
          <span className="badge green"><CheckCircle2 size={13} /> Ready</span>
        </div>}

        {mode === 'proxy' && <div className="connection-graphical-form">
          <div className="connection-form-group endpoint-group">
            <div className="connection-form-group-head"><span><Waypoints size={18} /></span><div><strong>Gateway Endpoint</strong><p>Set where D Bot should connect and which protocol it should use.</p></div></div>
            <div className="connection-protocol-card">
              <div className="connection-protocol-card-head"><span className="connection-field-icon"><Network size={18} /></span><div><strong>Proxy Protocol</strong><small>Choose the proxy protocol exposed by your gateway.</small></div></div>
              <div className="connection-protocol-picker" role="group" aria-label="Proxy Protocol">
                {(['socks5', 'socks4', 'http'] as const).map((protocol) => <button key={protocol} type="button" className={proxy.scheme === protocol ? 'active' : ''} onClick={() => setProxy({ ...proxy, scheme: protocol })}><span className="connection-protocol-dot" />{protocol === 'socks5' ? 'SOCKS5' : protocol === 'socks4' ? 'SOCKS4' : 'HTTP'}</button>)}
              </div>
            </div>
            <div className="connection-visual-form-grid endpoint-fields">
              <label className="connection-field-tile"><span className="connection-field-icon"><Server size={17} /></span><span className="connection-field-body"><span className="connection-field-label-row"><span className="connection-field-label">Proxy Port</span><small>Port</small></span><input inputMode="numeric" value={proxy.port} onChange={(e) => setProxy({ ...proxy, port: e.target.value })} placeholder="1080" /></span></label>
              <label className="connection-field-tile full host-field"><span className="connection-field-icon"><Globe2 size={17} /></span><span className="connection-field-body"><span className="connection-field-label-row"><span className="connection-field-label">Proxy Host</span><small>Endpoint</small></span><input value={proxy.host} onChange={(e) => setProxy({ ...proxy, host: e.target.value })} placeholder="proxy.example.com or 1.2.3.4" /><small>Domain or public IP reachable from this server.</small></span></label>
            </div>
            <div className="connection-endpoint-preview"><span><Wifi size={15} /></span><small>Endpoint Preview</small><strong>{proxy.host ? `${proxy.scheme}://${proxy.host}:${proxy.port || '—'}` : 'Waiting for gateway address'}</strong></div>
          </div>
          <div className="connection-form-group auth-group">
            <div className="connection-form-group-head"><span><KeyRound size={18} /></span><div><strong>Authentication</strong><p>Optional credentials are encrypted when saved.</p></div></div>
            <div className="connection-visual-form-grid auth-fields">
              <label className="connection-field-tile credential-field"><span className="connection-field-icon"><UserCog size={17} /></span><span className="connection-field-body"><span className="connection-field-label-row"><span className="connection-field-label">Proxy Username</span><small>Optional</small></span><input value={proxy.username} onChange={(e) => setProxy({ ...proxy, username: e.target.value })} placeholder="Optional" /></span></label>
              <label className="connection-field-tile credential-field"><span className="connection-field-icon"><KeyRound size={17} /></span><span className="connection-field-body"><span className="connection-field-label-row"><span className="connection-field-label">Proxy Password</span><small>{data.proxy?.password_configured ? 'Configured' : 'Optional'}</small></span><input type="password" value={proxy.password} onChange={(e) => setProxy({ ...proxy, password: e.target.value })} placeholder={data.proxy?.password_configured ? 'Configured — leave empty to keep current' : 'Optional'} /></span></label>
            </div>
            <div className="connection-credential-security"><ShieldCheck size={16} /><span><strong>Encrypted credentials</strong><small>Secrets are stored encrypted and are never returned to the browser after saving.</small></span></div>
          </div>
        </div>}

        {mode === 'v2ray' && <div className="connection-v2-block connection-v2-graphical">
          <div className="connection-v2-header"><span className="connection-panel-icon"><Network size={20} /></span><div><strong>Paste one share link</strong><p>D Bot will build the local Xray route automatically.</p></div></div>
          <label className="connection-share-link-card"><span className="connection-share-link-icon"><Network size={22} /></span><span className="connection-field-body"><span className="connection-field-label">V2 Share Link</span><textarea rows={6} value={v2Uri} onChange={(e) => setV2Uri(e.target.value)} placeholder={data.v2ray?.uri_configured ? 'Configured — paste a new link only to replace it' : 'vless://…  vmess://…  trojan://…  ss://…'} /></span></label>
          <div className="connection-protocol-strip"><span>VLESS</span><span>VMess</span><span>Trojan</span><span>Shadowsocks</span></div>
          <div className="connection-note-grid">
            <div><small>Supported protocols</small><strong>VLESS · VMess · Trojan · Shadowsocks</strong></div>
            <div><small>Saved protocol</small><strong>{data.v2ray?.protocol || 'Not configured'}</strong></div>
            <div><small>Xray runtime</small><strong>{data.v2ray?.xray_available ? 'Available' : 'Not installed in image'}</strong></div>
          </div>
          {data.v2ray?.uri_configured ? <p className="connection-secret-note"><ShieldCheck size={16} /> Saved V2 link is configured and encrypted. {data.v2ray.uri_preview ? `Preview: ${data.v2ray.uri_preview}` : ''}</p> : null}
          <p className="muted">Common TCP/RAW, WebSocket, gRPC, XHTTP/HTTPUpgrade transports plus TLS and REALITY share-link parameters are handled by the local Xray gateway.</p>
        </div>}

        {mode === 'mikrotik' && <div className="connection-graphical-form">
          <div className="connection-form-group endpoint-group mikrotik-endpoint-group">
            <div className="connection-form-group-head"><span><Router size={18} /></span><div><strong>Gateway Endpoint</strong><p>Enter the MikroTik SOCKS gateway reachable from the D Bot server.</p></div></div>
            <div className="connection-visual-form-grid endpoint-fields">
              <label className="connection-field-tile full host-field"><span className="connection-field-icon"><Globe2 size={17} /></span><span className="connection-field-body"><span className="connection-field-label-row"><span className="connection-field-label">MikroTik Host / IP</span><small>Endpoint</small></span><input value={mikrotik.host} onChange={(e) => setMikrotik({ ...mikrotik, host: e.target.value })} placeholder="192.0.2.10 or router.example.com" /><small>Router address reachable from the D Bot server.</small></span></label>
              <label className="connection-field-tile"><span className="connection-field-icon"><Server size={17} /></span><span className="connection-field-body"><span className="connection-field-label-row"><span className="connection-field-label">SOCKS Port</span><small>Port</small></span><input inputMode="numeric" value={mikrotik.port} onChange={(e) => setMikrotik({ ...mikrotik, port: e.target.value })} placeholder="1080" /></span></label>
            </div>
            <div className="connection-endpoint-preview"><span><Router size={15} /></span><small>Endpoint Preview</small><strong>{mikrotik.host ? `socks5://${mikrotik.host}:${mikrotik.port || '—'}` : 'Waiting for gateway address'}</strong></div>
          </div>
          <div className="connection-form-group auth-group">
            <div className="connection-form-group-head"><span><KeyRound size={18} /></span><div><strong>Authentication</strong><p>Optional credentials are encrypted when saved.</p></div></div>
            <div className="connection-visual-form-grid auth-fields">
              <label className="connection-field-tile credential-field"><span className="connection-field-icon"><UserCog size={17} /></span><span className="connection-field-body"><span className="connection-field-label-row"><span className="connection-field-label">SOCKS Username</span><small>Optional</small></span><input value={mikrotik.username} onChange={(e) => setMikrotik({ ...mikrotik, username: e.target.value })} placeholder="Optional" /></span></label>
              <label className="connection-field-tile credential-field"><span className="connection-field-icon"><KeyRound size={17} /></span><span className="connection-field-body"><span className="connection-field-label-row"><span className="connection-field-label">SOCKS Password</span><small>{data.mikrotik?.password_configured ? 'Configured' : 'Optional'}</small></span><input type="password" value={mikrotik.password} onChange={(e) => setMikrotik({ ...mikrotik, password: e.target.value })} placeholder={data.mikrotik?.password_configured ? 'Configured — leave empty to keep current' : 'Optional'} /></span></label>
            </div>
            <div className="connection-credential-security"><ShieldCheck size={16} /><span><strong>Encrypted credentials</strong><small>Secrets are stored encrypted and are never returned to the browser after saving.</small></span></div>
            <p className="connection-secret-note"><ShieldCheck size={16} /> RouterOS SOCKS/SOCKS5 must be enabled and reachable from the D Bot server. Restrict access to the bot server IP whenever possible.</p>
          </div>
        </div>}

        <div className="connection-action-panel">
          <div><span className="connection-section-kicker">Step 3</span><strong>Test before applying</strong><p>Verify Telegram reachability, then save the selected route.</p></div>
          <div className="connection-actions">
            <button className="btn" type="button" disabled={Boolean(busy)} onClick={testConnection}>{busy === 'test' ? <RefreshCw size={16} className="spin" /> : <Activity size={16} />} {busy === 'test' ? 'Testing…' : 'Test Telegram Connection'}</button>
            <button className="btn primary" type="button" disabled={Boolean(busy)} onClick={saveConnection}>{busy === 'save' ? <RefreshCw size={16} className="spin" /> : <Save size={16} />} {busy === 'save' ? 'Saving…' : 'Save & Apply'}</button>
          </div>
        </div>
      </section>

      <aside className="panel-card connection-status-card">
        <div className="connection-status-visual">
          <div className={`connection-status-orb ${lastStatus === 'ok' ? 'good' : lastStatus === 'failed' ? 'bad' : ''}`}><Wifi size={26} /></div>
          <div><span>Connection Status</span><strong>{statusText}</strong><small>{activeMode.title}</small></div>
        </div>
        <div className="connection-mini-stats">
          <div><Activity size={16} /><span><small>Latency</small><strong>{data.last_test?.latency_ms ? `${data.last_test.latency_ms} ms` : '—'}</strong></span></div>
          <div><Zap size={16} /><span><small>Applied mode</small><strong>{activeMode.title}</strong></span></div>
        </div>
        <dl>
          <div><dt>Last test</dt><dd><span className={`badge ${lastStatus === 'ok' ? 'green' : lastStatus === 'failed' ? 'red' : 'yellow'}`}>{statusText}</span></dd></div>
          <div><dt>Last test time</dt><dd>{data.last_test?.at ? shortDate(data.last_test.at) : '-'}</dd></div>
          <div><dt>Revision</dt><dd>{data.revision || '-'}</dd></div>
        </dl>
        {data.last_test?.message ? <div className={`connection-test-message ${lastStatus === 'failed' ? 'bad' : ''}`}>{data.last_test.message}</div> : null}
        <div className="connection-security"><ShieldCheck size={20} /><div><strong>Secrets stay protected</strong><p>Saved passwords and V2 links are encrypted in the database and are never returned to the browser.</p></div></div>
      </aside>
    </div>
  </div>;
}


function SettingsSection({ reloadKey, setAuthRequired, openModal, show }: any) {
  const { data, loading, error } = useApi<ApiList<SettingItem>>('/admin/api/v2/settings', reloadKey, setAuthRequired);
  if (loading) return <SkeletonGrid />;
  if (error || !data) return <EmptyState message={error || 'Settings could not be loaded.'} />;
  const map = Object.fromEntries(data.items.map((s) => [s.key, s.value]));
  const domain = String(map.web_domain || '').replace(/^https?:\/\//, '').replace(/\/$/, '');
  const baseUrl = domain ? `https://${domain}` : 'Not configured';
  const loginUrl = map.web_login_url || (domain ? `${baseUrl}/${map.web_path || 'dbot'}/login` : '-');

  return <div className="section-grid settings-grid">

    <EntityCard
      title="Website & SSL"
      icon={<Home />}
      badge={domain ? 'Online links' : 'Not configured'}
      badgeClass={domain ? 'green' : 'yellow'}
      kvs={[
        ['Website', baseUrl],
        ['Web Path', `/${map.web_path || 'dbot'}`],
        ['Login link', loginUrl],
        ['Admin panel', domain ? `${baseUrl}/${map.web_path || 'dbot'}/admin` : '-'],
        ['Username', map.web_admin_username || '-'],
        ['Password', map.web_password_configured === '1' ? 'Configured' : 'Not configured'],
        ['Session', `${map.web_token_timeout_minutes || 30} min`],
      ]}
      actions={<button className="btn primary" onClick={() => openModal(settingsWebsiteForm(map))}><KeyRound size={16} /> Edit Setup</button>}
    />

    <section className="card factory-reset-card">
      <div className="panel-head factory-reset-head">
        <div className="factory-reset-title">
          <span className="factory-reset-icon" aria-hidden="true"><Trash2 size={17} /></span>
          <div>
            <h2>Factory Reset</h2>
            <p className="muted">Erase local D BOT data and return this installation to first-run setup.</p>
          </div>
        </div>
        <span className="badge red">Danger Zone</span>
      </div>
      <div className="factory-reset-row">
        <div className="factory-reset-copy">
          <h3>Fresh-install reset</h3>
          <p className="muted">Removes plans, users, services, servers, settings, reports, backup configuration and customizations. External X-UI/MikroTik users are not modified.</p>
        </div>
        <button className="btn danger factory-reset-btn" type="button" onClick={async () => {
        if (!window.confirm('Factory Reset will permanently erase ALL D BOT database data and settings. Continue?')) return;
        const typed = window.prompt('Type FACTORY RESET to confirm:');
        if (typed !== 'FACTORY RESET') { show?.('Factory Reset cancelled. Confirmation text did not match.', false); return; }
        try {
          const result: any = await submitForm('/admin/settings/factory-reset', { confirm: 'FACTORY RESET' });
          show?.(result?.message || 'Factory Reset completed', true);
          window.setTimeout(() => { window.location.href = result?.redirect || publicWebPath('/setup'); }, 700);
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          if (msg === 'AUTH_REQUIRED') setAuthRequired(true);
          show?.(msg === 'AUTH_REQUIRED' ? 'Please login again' : msg, false);
        }
      }}><Trash2 size={16} /> Factory Reset</button></div>
    </section>
  </div>;
}


function BackupSection({ reloadKey, setAuthRequired, show }: any) {
  const { data, loading, error, setData } = useApi<BackupSettings>('/admin/api/v2/backup/settings', reloadKey, setAuthRequired);
  const [form, setForm] = useState<BackupFormState>({ destination: 'channel', sender_mode: 'current', secondary_bot_token: '', chat_id: '', interval_minutes: '1440', include_database: '1', include_files: '1' });
  const [test, setTest] = useState<BackupTestState>({ status: 'idle', message: '' });
  const [restoreFile, setRestoreFile] = useState<File | null>(null);
  const [legacySecret, setLegacySecret] = useState('');
  const [legacySecretKind, setLegacySecretKind] = useState<'auto' | 'fernet' | 'bot_token'>('auto');
  const [legacySecretRequired, setLegacySecretRequired] = useState(false);
  const [busy, setBusy] = useState('');

  useEffect(() => {
    if (!data?.settings) return;
    setForm({
      destination: data.settings.backup_destination || 'channel',
      sender_mode: data.settings.backup_sender_mode || 'current',
      secondary_bot_token: '',
      chat_id: data.settings.backup_chat_id || '',
      interval_minutes: data.settings.backup_interval_minutes || '1440',
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
      setTest({ status: res.ok === false ? 'bad' : 'ok', message: res.message || 'Fresh test message sent', adminOk: res.ok !== false });
      show(res.message || 'Fresh test message sent', res.ok !== false);
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

  async function sendSalesReportNow() {
    setBusy('sales-report');
    try {
      const result: any = await submitForm('/admin/reports/monthly-sales/run', {});
      show(result?.message || '30-day sales PDF report sent', true);
      const fresh = await fetchJson<BackupSettings>('/admin/api/v2/backup/settings');
      setData(fresh);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg === 'AUTH_REQUIRED') setAuthRequired(true);
      show(msg === 'AUTH_REQUIRED' ? 'Please login again' : msg, false);
    } finally { setBusy(''); }
  }

  async function restoreBackup() {
    if (!restoreFile) { show('Choose a JSON backup file first', false); return; }
    if (legacySecretRequired && !legacySecret.trim()) { show('Enter the old source FERNET_KEY or old bot token first', false); return; }
    if (!window.confirm('Restore and fully synchronize this backup? Current database data on this installation will be replaced.')) return;
    setBusy('restore');
    try {
      const fd = new FormData();
      fd.append('file', restoreFile);
      if (legacySecret.trim()) {
        fd.append('legacy_secret', legacySecret.trim());
        fd.append('legacy_secret_kind', legacySecretKind);
      }
      const res = await fetch('/admin/backup/restore', { method: 'POST', body: fd, credentials: 'include', headers: adminCsrfHeaders() });
      const json = await res.json().catch(() => null);
      if (!res.ok || !json?.ok) {
        if (json?.code === 'legacy_secret_required' || json?.code === 'legacy_secret_invalid') setLegacySecretRequired(true);
        throw new Error(json?.message || 'Restore failed');
      }
      show(json.message || 'Backup restored', true);
      setRestoreFile(null);
      setLegacySecret('');
      setLegacySecretRequired(false);
    } catch (err) { show(err instanceof Error ? err.message : String(err), false); } finally { setBusy(''); }
  }

  if (loading) return <SkeletonGrid />;
  if (error || !data) return <EmptyState message={error || 'Backup settings could not be loaded.'} />;
  const status = data.status || { configured: false };
  const secondaryConfigured = data.settings.backup_secondary_bot_configured === '1';
  const secondaryUsername = data.settings.backup_secondary_bot_username || '';
  const destinationLabel = form.destination === 'channel' ? 'Telegram Channel' : form.destination === 'group' ? 'Telegram Group' : 'Owner / Backup Bot DM';
  const senderLabel = form.sender_mode === 'secondary' ? (secondaryUsername ? `Secondary bot @${secondaryUsername}` : 'Secondary backup bot') : 'Current D BOT';
  const intervalLabel = ({ '60': 'Every 1 hour', '180': 'Every 3 hours', '360': 'Every 6 hours', '720': 'Every 12 hours', '1440': 'Every 24 hours', '10080': 'Every 7 days' } as Record<string, string>)[form.interval_minutes] || `${form.interval_minutes} min`;

  return <div className="section-grid backup-grid">
    <section className="card backup-settings-card">
      <div className="panel-head"><h2>Backup Delivery</h2><span className={`badge ${status.configured ? 'green' : 'yellow'}`}>{status.configured ? 'Configured' : 'Not configured'}</span></div>
      <div className="form-grid compact-form">
        <label className="form-field"><span>Sender bot</span><select value={form.sender_mode} onChange={(e) => setField('sender_mode', e.target.value)}><option value="current">Current D BOT</option><option value="secondary">Secondary backup bot</option></select></label>
        <label className="form-field"><span>Backup cycle</span><select value={form.interval_minutes} onChange={(e) => setField('interval_minutes', e.target.value)}><option value="60">Every 1 hour</option><option value="180">Every 3 hours</option><option value="360">Every 6 hours</option><option value="720">Every 12 hours</option><option value="1440">Every 24 hours</option><option value="10080">Every 7 days</option></select></label>
        {form.sender_mode === 'secondary' && <label className="form-field full"><span>Secondary bot token</span><input type="password" autoComplete="off" value={form.secondary_bot_token} onChange={(e) => setField('secondary_bot_token', e.target.value)} placeholder={secondaryConfigured ? 'Configured — leave empty to keep current token' : 'Enter token from @BotFather'} /><small>{secondaryConfigured ? `Secondary bot is configured${secondaryUsername ? ` as @${secondaryUsername}` : ''}. Enter a token only when you want to replace it.` : 'After saving the token, the second bot starts automatically and exposes backup controls to owner IDs only.'}</small></label>}
        <label className="form-field"><span>Send backup to</span><select value={form.destination} onChange={(e) => setField('destination', e.target.value)}><option value="channel">Channel</option><option value="group">Group</option><option value="bot">Owner / bot chat</option></select></label>
        {form.destination === 'bot' && <label className="form-field"><span>Owner chat ID</span><input value={form.chat_id} onChange={(e) => setField('chat_id', e.target.value)} placeholder="Leave empty to use first OWNER_ID" /></label>}
        {form.destination === 'channel' && <label className="form-field full"><span>Channel address</span><input value={form.chat_id} onChange={(e) => setField('chat_id', e.target.value)} placeholder="@channel, -100..., or https://t.me/c/.../post" /><small>The selected sender bot must already be added to this channel as Administrator with Send/Post Messages enabled. Every Test click sends a new message.</small></label>}
        {form.destination === 'group' && <label className="form-field full"><span>Group address</span><input value={form.chat_id} onChange={(e) => setField('chat_id', e.target.value)} placeholder="@group, -100..., or https://t.me/c/.../message" /><small>The selected sender bot must be an Administrator in the group and able to send messages. Every Test click sends a new message.</small></label>}
        <label className="form-field"><span>Database backup</span><select value={form.include_database} onChange={(e) => setField('include_database', e.target.value)}><option value="1">Enabled</option><option value="0">Disabled</option></select></label>
        <label className="form-field"><span>Files backup</span><select value={form.include_files} onChange={(e) => setField('include_files', e.target.value)}><option value="1">Enabled</option><option value="0">Disabled</option></select></label>
      </div>
      <div className="card-actions"><button className="btn primary" disabled={busy === 'save'} onClick={saveSettings}><Save size={16} /> Save</button><button className="btn success" disabled={busy === 'test'} onClick={testDestination}><CheckCircle2 size={16} /> Send Fresh Test Message</button><button className="btn" disabled={busy === 'backup'} onClick={runBackup}><Archive size={16} /> Send Backup Now</button><button className="btn" disabled={busy === 'sales-report'} onClick={sendSalesReportNow}><FileText size={16} /> Send Sales Report Now</button></div>
      <div className={`backup-test-result ${test.status}`}><span>{test.status === 'ok' ? <CheckCircle2 size={18} /> : test.status === 'bad' ? <XCircle size={18} /> : <Bot size={18} />}</span><b>{test.status === 'idle' ? 'No destination test yet' : 'Backup delivery test'}</b><p>{test.message || 'Test validates the bot token, confirms admin status for channels/groups, checks send permission, and creates a brand-new Telegram message on every click.'}</p></div>
    </section>

    <EntityCard title="Backup & Sales Reports" icon={<Archive />} badge={status.last_sales_report_status === 'ok' ? 'Sales PDF OK' : status.last_backup_status === 'ok' ? 'Last backup OK' : status.last_backup_status === 'error' ? 'Last backup error' : 'Portable v4'} badgeClass={status.last_sales_report_status === 'ok' ? 'green' : status.last_backup_status === 'ok' ? 'green' : status.last_backup_status === 'error' ? 'red' : 'purple'} kvs={[["Sender", senderLabel], ["Destination", destinationLabel], ['Target', form.chat_id || (form.destination === 'bot' ? 'First OWNER_ID' : '-')], ['Backup cycle', intervalLabel], ['Sales PDF cycle', 'Every 30 days'], ['Last backup', status.last_backup_at ? shortDate(status.last_backup_at) : '-'], ['Last sales PDF', status.last_sales_report_at ? shortDate(status.last_sales_report_at) : '-'], ['Sales PDF status', status.last_sales_report_message || 'Uses the same Telegram destination as backups']]} actions={<a className="btn" href={publicWebPath('/admin/backup/download')}><Download size={15} /> Download Portable JSON</a>} />

    <section className="card restore-card">
      <div className="panel-head"><h2>Restore Portable Backup</h2><span className="badge yellow">Cross-install Sync</span></div>
      <p className="muted">Upload a D BOT portable JSON backup on any VPS or installation. All supported database tables are synchronized, server credentials and encrypted backup-bot/web secrets are re-encrypted for this installation, and database sequences are reset.</p>
      <label className="restore-drop"><Upload size={28} /><b>{restoreFile ? restoreFile.name : 'Choose portable backup file'}</b><small>JSON only · keep this file private because it contains recoverable service credentials</small><input type="file" accept="application/json,.json" onChange={(e) => { setRestoreFile(e.target.files?.[0] || null); setLegacySecretRequired(false); setLegacySecret(''); }} /></label>
      <details className="backup-test-result" open={legacySecretRequired}>
        <summary><b>Restore an old format 1–3 backup</b></summary>
        <p className="muted">Old backups stored server passwords with the source VPS key. Paste the old FERNET_KEY shown by <code>dbot credentials</code>. When that VPS had no FERNET_KEY, paste its old Telegram bot token instead. The value is used once and is never saved.</p>
        <div className="form-grid compact-form">
          <label className="form-field"><span>Source secret type</span><select value={legacySecretKind} onChange={(e) => setLegacySecretKind(e.target.value as 'auto' | 'fernet' | 'bot_token')}><option value="auto">Auto detect</option><option value="fernet">Old FERNET_KEY</option><option value="bot_token">Old Telegram bot token</option></select></label>
          <label className="form-field full"><span>Old source secret</span><input type="password" autoComplete="off" value={legacySecret} onChange={(e) => setLegacySecret(e.target.value)} placeholder="Paste the source FERNET_KEY or old bot token" /></label>
        </div>
      </details>
      <div className="card-actions"><button className="btn danger" disabled={!restoreFile || busy === 'restore'} onClick={restoreBackup}><Upload size={16} /> {legacySecretRequired ? 'Unlock, Restore & Sync' : 'Restore & Sync'}</button></div>
    </section>
  </div>;
}


function TestAccountSection({ reloadKey, setAuthRequired, show }: any) {
  const { data, loading, error, setData } = useApi<TestAccountApi>('/admin/api/v2/test-account', reloadKey, setAuthRequired);
  const [form, setForm] = useState<{ enabled: string; button_visible: string; targets: TestAccountTarget[]; volume_gb: string; duration_days: string }>({ enabled: '1', button_visible: '1', targets: [], volume_gb: '1', duration_days: '1' });
  const [saving, setSaving] = useState(false);
  const [deleteTelegramId, setDeleteTelegramId] = useState('');

  function serverInbounds(server?: ServerItem): { id: number; remark?: string; protocol?: string }[] {
    if (!server || server.server_type === 'mikrotik') return [];
    const rows = server.inbounds?.length
      ? server.inbounds
      : (server.inbound_ids || []).map((raw: any) => ({ id: Number(typeof raw === 'object' ? raw.id : raw), remark: `Inbound ${typeof raw === 'object' ? raw.id : raw}`, protocol: '' }));
    const seen = new Set<number>();
    return (rows || []).filter((item: any) => {
      const id = Number(item?.id || 0);
      if (id <= 0 || seen.has(id)) return false;
      seen.add(id);
      return true;
    }).map((item: any) => ({ id: Number(item.id), remark: item.remark, protocol: item.protocol }));
  }

  useEffect(() => {
    if (!data?.settings) return;
    let targets: TestAccountTarget[] = Array.isArray(data.targets) ? data.targets.map((x) => ({ server_id: Number(x.server_id), inbound_ids: (x.inbound_ids || []).map(Number).filter((n) => n > 0) })) : [];
    if (!targets.length && Number(data.settings.server_id || 0) > 0) {
      targets = [{ server_id: Number(data.settings.server_id), inbound_ids: String(data.settings.inbound_ids || '').split(/[\s,]+/).filter(Boolean).map(Number).filter((n) => n > 0) }];
    }
    setForm({
      enabled: data.settings.enabled || '1',
      button_visible: data.settings.button_visible || '1',
      targets,
      volume_gb: data.settings.volume_gb || '1',
      duration_days: data.settings.duration_days || '1'
    });
  }, [data]);

  if (loading) return <SkeletonGrid />;
  if (error || !data) return <EmptyState message={error || 'Test account settings could not be loaded.'} />;

  const publicServers = data.servers.filter((server) => server.is_active && server.scope !== 'reseller');
  const targetFor = (serverId: number) => form.targets.find((target) => Number(target.server_id) === Number(serverId));
  const selectedServers = publicServers.filter((server) => Boolean(targetFor(server.id)));
  const totalInboundCount = form.targets.reduce((sum, target) => sum + (target.inbound_ids || []).length, 0);

  function toggleServer(server: ServerItem) {
    const current = targetFor(server.id);
    if (current) {
      setForm((prev) => ({ ...prev, targets: prev.targets.filter((target) => target.server_id !== server.id) }));
      return;
    }
    const defaults = serverInbounds(server).map((item) => item.id);
    setForm((prev) => ({ ...prev, targets: [...prev.targets, { server_id: server.id, inbound_ids: defaults }] }));
  }

  function setServerInbounds(serverId: number, inboundIds: number[]) {
    const clean = Array.from(new Set(inboundIds.map(Number).filter((id) => id > 0))).sort((a, b) => a - b);
    setForm((prev) => ({
      ...prev,
      targets: prev.targets.map((target) => target.server_id === serverId ? { ...target, inbound_ids: clean } : target)
    }));
  }

  function toggleInbound(serverId: number, inboundId: number) {
    const target = targetFor(serverId);
    if (!target) return;
    const selected = new Set(target.inbound_ids || []);
    if (selected.has(inboundId)) selected.delete(inboundId); else selected.add(inboundId);
    setServerInbounds(serverId, Array.from(selected));
  }

  async function save() {
    if (!data) { show('Test account settings are not loaded yet', false); return; }
    if (!form.targets.length) { show('Select at least one server for test accounts', false); return; }
    for (const target of form.targets) {
      const server = data.servers.find((item) => item.id === target.server_id);
      if (server?.server_type === 'xui' && !(target.inbound_ids || []).length) {
        show(`Select at least one inbound for ${server.display_name || server.name}`, false);
        return;
      }
    }
    setSaving(true);
    try {
      const first = form.targets[0];
      await submitForm('/admin/test-account/save', {
        enabled: form.enabled,
        button_visible: form.button_visible,
        targets_json: JSON.stringify(form.targets),
        server_id: String(first?.server_id || 0),
        inbound_ids: (first?.inbound_ids || []).join(','),
        volume_gb: form.volume_gb,
        duration_days: form.duration_days
      });
      const fresh = await fetchJson<TestAccountApi>('/admin/api/v2/test-account');
      setData(fresh);
      show(`Test account settings saved for ${form.targets.length} server(s)`, true);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg === 'AUTH_REQUIRED') setAuthRequired(true);
      show(msg === 'AUTH_REQUIRED' ? 'Please login again' : msg, false);
    } finally { setSaving(false); }
  }

  async function resetUsage() {
    if (!window.confirm('Reset test account usage history? Users will be able to receive test accounts again.')) return;
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
    if (!window.confirm(`Remove test account usage for Telegram ID ${tg}? This user will be able to receive test accounts again.`)) return;
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
      <h2>Multi-Server Trial Accounts</h2>
      <p className="muted">Select any combination of Sanaei / X-UI, PasarGuard and MikroTik / OpenVPN servers. One user request creates one independent trial account on every selected server.</p>
      <div className="kvs">
        <div className="kv"><span>Status</span><b>{form.enabled === '1' ? 'Enabled' : 'Disabled'}</b></div>
        <div className="kv"><span>Button</span><b>{form.button_visible === '1' ? 'Visible' : 'Hidden'}</b></div>
        <div className="kv"><span>Selected servers</span><b>{selectedServers.length}</b></div>
        <div className="kv"><span>Used by users</span><b>{data.usage_count}</b></div>
      </div>
      <div className="card-actions"><button className="btn danger" onClick={resetUsage}><Trash2 size={16} /> Reset usage history</button></div>
    </section>

    <section className="card test-account-settings">
      <div className="panel-head"><h2>Test Account Settings</h2><span className={`badge ${form.enabled === '1' ? 'green' : 'red'}`}>{form.enabled === '1' ? 'Active' : 'Inactive'}</span></div>
      <div className="form-grid">
        <label className="form-field"><span>Test account status</span><select value={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.value })}><option value="1">Enabled</option><option value="0">Disabled</option></select></label>
        <label className="form-field"><span>Bot button visibility</span><select value={form.button_visible} onChange={(e) => setForm({ ...form, button_visible: e.target.value })}><option value="1">Show button</option><option value="0">Hide button</option></select></label>
        <label className="form-field"><span>Volume per server (GB)</span><input type="number" min="0.1" step="0.1" value={form.volume_gb} onChange={(e) => setForm({ ...form, volume_gb: e.target.value })} /></label>
        <label className="form-field"><span>Duration per server (days)</span><input type="number" min="1" value={form.duration_days} onChange={(e) => setForm({ ...form, duration_days: e.target.value })} /></label>
      </div>

      <div className="test-server-picker">
        <div className="test-server-picker-head"><div><b>Trial servers</b><p className="muted">Select one or more servers. Inbound selection is stored separately for each server.</p></div><span className="badge">{form.targets.length} selected</span></div>
        {publicServers.length ? publicServers.map((server) => {
          const target = targetFor(server.id);
          const selected = Boolean(target);
          const inbounds = serverInbounds(server);
          const selectedInboundIds = new Set(target?.inbound_ids || []);
          const provider = server.server_type === 'pasarguard' ? 'PasarGuard' : server.server_type === 'mikrotik' ? 'MikroTik / OpenVPN' : 'Sanaei / X-UI';
          return <div key={server.id} className={`test-server-row ${selected ? 'selected' : ''}`}>
            <div className="test-server-main">
              <button type="button" className={`btn ${selected ? 'success' : ''}`} onClick={() => toggleServer(server)}>{selected ? '✓ Selected' : '+ Select'}</button>
              <div className="test-server-name"><b>{server.display_name || server.name}</b><span>{provider} · ID {server.id}</span></div>
              <span className={`badge ${selected ? 'green' : ''}`}>{selected ? 'Included' : 'Not selected'}</span>
            </div>
            {selected && <div className="test-server-inbounds">
              {server.server_type === 'mikrotik' ? <p className="muted">OpenVPN / MikroTik does not require Inbound selection. One trial user will be created on this server.</p> : inbounds.length ? <>
                <div className="inbound-toolbar"><span>Inbounds / Groups for this server</span><button className="btn mini" type="button" onClick={() => setServerInbounds(server.id, inbounds.map((item) => item.id))}>Select all</button></div>
                <div className="test-inbound-list">{inbounds.map((inbound) => <button type="button" key={inbound.id} className={`inbound-chip ${selectedInboundIds.has(inbound.id) ? 'selected' : ''}`} onClick={() => toggleInbound(server.id, inbound.id)}><b>#{inbound.id}</b><span>{inbound.remark || `Inbound ${inbound.id}`}</span><small>{inbound.protocol || (server.server_type === 'pasarguard' ? 'group' : 'x-ui')}</small></button>)}</div>
              </> : <p className="muted">No inbound/group list is exposed by this server. PasarGuard can use its automatic template/group policy; X-UI must be refreshed before saving.</p>}
            </div>}
          </div>;
        }) : <EmptyInline />}
      </div>

      <div className="test-summary"><div><b>{form.targets.length}</b><span>Trial servers</span></div><div><b>{totalInboundCount}</b><span>Selected inbounds</span></div><div><b>{form.volume_gb} GB</b><span>Per server</span></div><div><b>{form.duration_days} days</b><span>Per server</span></div></div>
      <div className="card-actions"><button className="btn primary" disabled={saving || !form.targets.length} onClick={save}><Save size={16} /> Save Multi-Server Test Account</button></div>
    </section>

    <section className="card table-card test-usage-card">
      <div className="panel-head"><h2>Users who used test account</h2><span className="badge">{data.usage_count} total</span></div>
      <div className="filterbar compact-filter"><label className="form-field"><span>User Telegram ID</span><input value={deleteTelegramId} onChange={(e) => setDeleteTelegramId(e.target.value)} placeholder="Search and remove one user" /></label><button className="btn danger" onClick={deleteSingleUsage}><Search size={16} /> Remove this user</button></div>
      <div className="table-scroll"><table><thead><tr><th>User</th><th>Telegram ID</th><th>First trial service</th><th>Date</th><th>Action</th></tr></thead><tbody>{(data.usage_items || []).length ? (data.usage_items || []).map((u) => <tr key={u.id}><td>{u.user?.full_name || u.user?.username || '-'}</td><td>{u.telegram_id}</td><td>{u.service_id ? `#${u.service_id}` : '-'}</td><td>{shortDate(u.created_at)}</td><td><button className="btn mini danger" onClick={() => { setDeleteTelegramId(String(u.telegram_id)); }}><Trash2 size={14} /> Select</button></td></tr>) : <tr><td colSpan={5}><EmptyInline /></td></tr>}</tbody></table></div>
      <div className="card-actions"><button className="btn danger" onClick={resetUsage}><Trash2 size={16} /> Reset all test-account users</button></div>
    </section>
  </div>;
}

function ServiceTypesSection({ reloadKey, setAuthRequired, openModal, runAction, show }: any) {
  const { data, loading, error, setData } = useApi<ApiList<ServiceTypeItem>>('/api/admin/service-types?v=1.2.0-provider-routing', reloadKey, setAuthRequired);
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
  return <><div className="filterbar"><button className="btn primary" onClick={() => openModal(serviceTypeForm())}><Plus size={16} /> Add Service Type</button><span className="badge">{serviceTypes.length} custom types</span>{savingOrder && <span className="badge yellow">Saving order...</span>}</div><div className="plan-order-note"><ListChecks size={16} /> Each service type must route to the backend provider that owns its plans. Use PasarGuard for PasarGuard servers, X-UI for 3x-ui/Sanaei, or MikroTik for OpenVPN/L2TP. Auto mode keeps backward-compatible detection.</div><div className="section-grid">{serviceTypes.length ? serviceTypes.map((s) => { const providerLabel = s.server_type === 'pasarguard' ? 'PasarGuard' : s.server_type === 'mikrotik' ? 'MikroTik / OpenVPN' : 'X-UI / 3x-ui'; return <div key={s.key} className={`drag-card ${dragKey === s.key ? 'dragging' : ''}`} draggable onDragStart={() => setDragKey(s.key)} onDragOver={(e) => e.preventDefault()} onDrop={() => dropOn(s.key)} onDragEnd={() => setDragKey('')}><EntityCard title={s.value} icon={<ListChecks />} badge={s.is_active ? 'Active' : 'Inactive'} badgeClass={s.is_active ? 'green' : 'red'} kvs={[["Value", s.value], ['Backend provider', s.server_type_mode === 'manual' ? providerLabel : `Auto → ${providerLabel}`], ['Display order', serviceTypes.findIndex((x) => x.key === s.key) + 1]]} actions={<><span className="drag-handle"><ListChecks size={15} /> Drag</span><button className="btn" onClick={() => openModal(serviceTypeForm(s))}>Edit</button><button className={s.is_active ? 'btn danger' : 'btn success'} onClick={() => runAction(`/admin/service-types/toggle?key=${encodeURIComponent(s.key)}`, s.is_active ? 'Service type deactivated' : 'Service type activated')}>{s.is_active ? 'Deactivate' : 'Activate'}</button><button className="btn danger" onClick={() => runAction(`/admin/service-types/delete?key=${encodeURIComponent(s.key)}`, 'Service type deleted')}>Delete</button></>} /></div>; }) : <EmptyState message="No custom service type found. Add V2Ray, OpenVPN, or any other service from here." />}</div></>;
}

function EntityCard({ title, icon, badge, badgeClass = 'purple', kvs, actions, headingLevel = 2 }: { title: string; icon: React.ReactNode; badge?: string; badgeClass?: string; kvs: [string, any][]; actions?: React.ReactNode; headingLevel?: 2 | 3 }) {
  const Heading = headingLevel === 3 ? 'h3' : 'h2';
  return <motion.section className="card entity-card" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} tabIndex={0}><div className="panel-head"><Heading className="row-left"><span className="tiny-avatar">{icon}</span>{title}</Heading>{badge && <span className={`badge ${badgeClass}`}>{badge}</span>}</div><div className="kvs">{kvs.map(([k, v]) => <div className="kv" key={k}><span>{k}</span><b>{String(v ?? '-')}</b></div>)}</div>{actions && <div className="card-actions">{actions}</div>}</motion.section>;
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
      if (name === 'server_id') { next.inbound_ids = ''; next.group_name = ''; }
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
      current = label.includes('mikrotik') || label.includes('microtik') || label.includes('mikrotik / custom')
        ? 'mikrotik'
        : label.includes('pasarguard') ? 'pasarguard'
        : label.includes('openvpn') ? 'openvpn' : 'xui';
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
  return <div className="modal-backdrop"><motion.div className="modal-card" initial={{ scale: .96, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}><div className="modal-head"><h2>{modal.title}</h2><button className="icon-btn" onClick={onClose}><X size={18} /></button></div><form className="form-grid" onSubmit={submitCurrentForm}>{modal.fields.filter((f) => !f.hidden).filter(visible).map((field) => <label key={field.name} className={`form-field ${field.full ? 'full' : ''}`}><span>{field.label}</span>{field.type === 'user-search' ? <UserSearchField onPick={mergeUser} /> : field.type === 'textarea' ? <textarea required={field.required} placeholder={field.placeholder} value={values[field.name] || ''} onChange={(e) => change(field.name, e.target.value)} /> : field.type === 'checkbox-group' ? <div className="checkbox-grid">{fieldOptions(field).filter((o) => String(o.value) !== '0').map((o) => { const value = String(o.value); const checked = csvValues(field.name).includes(value); return <label key={value} className={`checkline ${checked ? 'checked' : ''}`}><input type="checkbox" checked={checked} onChange={(e) => toggleCsvValue(field.name, value, e.currentTarget.checked)} /><span className="checkmark" aria-hidden="true">{checked ? '✓' : ''}</span><span className="checktext">{o.label}</span></label>; })}</div> : field.type === 'multiselect' ? <div className="multi-picker"><div className="multi-picker-toolbar"><span className="multi-picker-count">{csvValues(field.name).length} selected</span><div className="multi-picker-actions"><button type="button" className="btn mini" onClick={() => setAllMultiValues(field)}>Select all</button><button type="button" className="btn mini" onClick={() => change(field.name, '')}>Clear all</button></div></div><div className="checkbox-grid multi-checkbox-grid">{fieldOptions(field).filter((o) => String(o.value) !== '0').map((o) => { const value = String(o.value); const checked = csvValues(field.name).includes(value); return <button type="button" key={value} role="checkbox" aria-checked={checked} className={`checkline multi-checkline ${checked ? 'checked' : ''}`} onClick={() => toggleCsvValue(field.name, value, !checked)}><span className="checkmark" aria-hidden="true">{checked ? '✓' : ''}</span><span className="checktext">{o.label}</span></button>; })}</div>{fieldOptions(field).length === 0 && <p className="muted multi-picker-empty">No inbound is available for the selected server. Run Servers → Test &amp; Auto Fill first.</p>}<input type="hidden" value={values[field.name] || ''} readOnly /></div> : field.type === 'select' ? <select required={field.required} value={values[field.name] || ''} onChange={(e) => change(field.name, e.target.value)}>{fieldOptions(field).map((o) => <option key={String(o.value)} value={String(o.value)}>{o.label}</option>)}</select> : field.type === 'file' ? <input type="file" required={field.required} accept={field.placeholder || '.ovpn'} onChange={(e) => change(field.name, e.target.files?.[0] || null)} /> : <input type={field.type || 'text'} required={field.required} placeholder={field.placeholder} step={field.step} min={field.min} value={values[field.name] || ''} onChange={(e) => change(field.name, e.target.value)} />}</label>)}<div className="form-actions">{isNewServer && <button type="button" className="btn success" disabled={testing} onClick={testServerConnection}><CheckCircle2 size={16} /> {testing ? 'Testing...' : 'Test & Auto Fill'}</button>}<button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn primary" type="submit">Save</button></div></form></motion.div></div>;
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
function serverOptions(items: ServerItem[]) { return [{ value: 0, label: 'Select server' }, ...items.map((s) => ({ value: s.id, label: `${s.display_name || s.name} (${s.server_type === 'mikrotik' ? 'MikroTik / Custom' : (s.server_type === 'pasarguard' ? 'PasarGuard' : s.server_type)})` }))]; }
function categoryOptions(items: CategoryItem[]) { return [{ value: 0, label: 'Select category' }, ...items.map((c) => ({ value: c.id, label: `${c.name}${c.server_names?.length ? ` (${c.server_names.join(', ')})` : (c.server_id ? ` (Server #${c.server_id})` : '')}` }))]; }
function commonScopeOptions() { return [{ value: 'public', label: 'Public sales' }, { value: 'reseller', label: 'Reseller' }, { value: 'all', label: 'Public + Reseller' }]; }

function serverForm(s?: ServerItem): ModalForm {
  const isCustom = s?.server_type === 'mikrotik';
  const isPasarGuard = s?.server_type === 'pasarguard';
  const defaults = s ? {
    ...s,
    server_type: isCustom ? 'mikrotik' : (isPasarGuard ? 'pasarguard' : 'xui'),
    scope: s.scope || (isCustom ? 'all' : 'public'),
    panel_url: isCustom ? (s.panel_base_url || s.panel_url || '') : (s.panel_base_url || s.panel_url || ''),
    panel_path: (isCustom || isPasarGuard) ? '/' : (s.panel_path || '/'),
    subscription_url: (isCustom || isPasarGuard) ? '' : (s.subscription_url || ''),
    username: isCustom ? (s.auth_username || '') : (s.username || ''),
    name: isCustom ? (s.name || 'custom-panel') : (s.name || ''),
    display_name: s.display_name || s.name || '',
    detected_routers: isCustom ? (s.router_name || '') : '',
    api_key: '',
    l2tp_server: s.l2tp_server || 'vpn.example.com',
    l2tp_ipsec_secret: s.l2tp_ipsec_secret || 'CHANGE_ME_IPSEC_SECRET',
    badge_color: s.badge_color || (isCustom ? '#f97316' : (isPasarGuard ? '#22c55e' : '#2563eb')),
    badge_emoji: circleEmojiForColor(s.badge_color || (isCustom ? '#f97316' : (isPasarGuard ? '#22c55e' : '#2563eb'))),
    badge_label: s.badge_label || (isCustom ? 'MikroTik / OpenVPN' : (isPasarGuard ? 'PasarGuard' : 'V2Ray')),
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
      { name: 'server_type', label: 'Profile', type: 'select', options: [{ value: 'xui', label: 'Sanaei / 3x-ui' }, { value: 'pasarguard', label: 'PasarGuard' }, { value: 'mikrotik', label: 'MikroTik / Custom' }] },
      { name: 'scope', label: 'Show this server for', type: 'select', options: commonScopeOptions() },
      { name: 'name', label: 'Server name shown to users', required: true, placeholder: 'Germany / DE / OpenVPN Germany' },
      { name: 'display_name', label: 'Display name', placeholder: 'Optional bot/admin display name' },
      { name: 'badge_label', label: 'Service badge text shown to users', placeholder: 'V2Ray or MikroTik / OpenVPN' },
      { name: 'badge_color', label: 'Circle color in website', type: 'color' },
      { name: 'badge_emoji', label: 'Circle emoji in bot (auto from color)', placeholder: 'Auto based on Circle color' },
      { name: 'panel_url', label: 'Panel URL / Origin', required: true, full: true, placeholder: 'https://panel.example.com' },
      { name: 'panel_path', label: 'Panel Web Path', placeholder: '/secretpath/', showWhen: { name: 'server_type', value: 'xui' } },
      { name: 'subscription_url', label: 'Subscription URL', full: true, placeholder: 'https://sub.example.com/sub/', showWhen: { name: 'server_type', value: 'xui' } },
      { name: 'username', label: 'Username', required: false },
      { name: 'password', label: s ? 'New password / login password' : 'Password / login password', type: 'password', required: false },
      { name: 'api_key', label: 'API Token Panel', type: 'password', full: true, placeholder: 'Optional panel API token/key. Supported by 3x-ui, PasarGuard and MikroTik.' },
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
  const groupOptionsByServer: Record<string, { value: string | number; label: string }[]> = {};
  for (const server of servers) {
    groupOptionsByServer[String(server.id)] = [
      { value: '', label: 'No client group' },
      ...(server.client_groups || []).map((group) => ({
        value: group.name,
        label: group.client_count == null ? group.name : `${group.name} (${group.client_count} clients)`,
      })),
    ];
  }
  // Preserve an already-saved group if the panel is temporarily unreachable
  // while editing. This prevents a harmless group-list timeout from clearing
  // the plan's current policy when the form is saved.
  if (p?.server_id && p.group_name) {
    const key = String(p.server_id);
    const options = groupOptionsByServer[key] || [{ value: '', label: 'No client group' }];
    if (!options.some((option) => String(option.value) === String(p.group_name))) {
      options.push({ value: p.group_name, label: `${p.group_name} (current)` });
    }
    groupOptionsByServer[key] = options;
  }
  const inboundMode = p?.inbound_mode || 'automatic';
  return {
    title: p ? 'Edit Public Plan' : 'Add Plan',
    action: p ? `/admin/plans/${p.id}/edit` : '/admin/plans/add',
    defaults: p ? { ...p, plan_kind: 'public', pricing_currency: p.pricing_currency || 'IRT', price_usd: p.price_usd || '', inbound_mode: inboundMode, group_name: p.group_name || '', hwid_limit: Number(p.hwid_limit || 0) } : { plan_kind: 'public', pricing_currency: 'IRT', price_irt: 0, price_usd: '', category_id: 0, server_id: 0, reseller_validity_days: 365, inbound_mode: 'automatic', inbound_ids: [], group_name: '', hwid_limit: 0 },
    fields: [
      { name: 'plan_kind', label: 'Plan is for', type: 'select', options: [{ value: 'public', label: 'Public' }, { value: 'reseller', label: 'Resellers' }], hidden: !!p },
      { name: 'title', label: 'Plan title', required: true },
      { name: 'pricing_currency', label: 'Pricing currency', type: 'select', options: [{ value: 'IRT', label: 'Toman — fixed price' }, { value: 'USD', label: 'USD — live Wallex rate at checkout' }], required: true },
      { name: 'price_irt', label: 'Price (Toman)', type: 'number', required: true, min: 0, showWhen: { name: 'pricing_currency', value: 'IRT' } },
      { name: 'price_usd', label: 'Price (USD)', type: 'number', required: true, min: 0.01, step: 0.01, placeholder: 'Example: 4.99', showWhen: { name: 'pricing_currency', value: 'USD' } },
      { name: 'volume_gb', label: 'Volume GB', type: 'number', required: true },
      { name: 'duration_days', label: 'Duration days', type: 'number', required: true, showWhen: { name: 'plan_kind', value: 'public' } },
      { name: 'reseller_validity_days', label: 'Reseller validity days', type: 'number', required: true, showWhen: { name: 'plan_kind', value: 'reseller' } },
      { name: 'category_id', label: 'Select category', type: 'select', options: catOptions, required: true, showWhen: { name: 'plan_kind', value: 'public' } },
      { name: 'server_id', label: 'Select server', type: 'select', options: serverOptionsList, required: true },
      { name: 'hwid_limit', label: 'HWID device limit (0 = unlimited)', type: 'number', required: true, min: 0, step: 1, placeholder: 'Example: 1 device', showWhenAll: [{ name: 'plan_kind', value: 'public' }, { name: '__selected_server_type', values: ['xui','pasarguard'] }] },
      { name: 'group_name', label: 'Sanaei client group', type: 'select', optionsBy: { name: 'server_id', map: groupOptionsByServer }, full: true, showWhenAll: [{ name: 'plan_kind', value: 'public' }, { name: '__selected_server_type', value: 'xui' }] },
      { name: 'inbound_mode', label: 'Inbound / group selection mode', type: 'select', options: [{ value: 'automatic', label: 'Automatic — use all active inbounds / groups' }, { value: 'manual', label: 'Manual — choose specific inbounds / groups' }], required: true, full: true, showWhenAll: [{ name: 'plan_kind', value: 'public' }, { name: '__selected_server_type', values: ['xui','pasarguard'] }] },
      { name: 'inbound_ids', label: 'Inbounds / PasarGuard groups included in this plan', type: 'multiselect', optionsBy: { name: 'server_id', map: inboundOptionsByServer }, required: true, full: true, showWhenAll: [{ name: 'plan_kind', value: 'public' }, { name: '__selected_server_type', values: ['xui','pasarguard'] }, { name: 'inbound_mode', value: 'manual' }] }
    ]
  };
}
function resellerPlanForm(serverOptionsList: any[], p?: ResellerPackage): ModalForm { return { title: 'Edit Reseller Plan', action: p ? `/admin/plans/reseller/${p.id}/edit` : '/admin/plans/add', defaults: p ? { ...p, plan_kind: 'reseller', pricing_currency: p.pricing_currency || 'IRT', price_usd: p.price_usd || '' } : { plan_kind: 'reseller', reseller_validity_days: 365, server_id: 0, pricing_currency: 'IRT', price_irt: 0, price_usd: '' }, fields: [{ name: 'plan_kind', label: 'Plan is for', type: 'select', options: [{ value: 'public', label: 'Public' }, { value: 'reseller', label: 'Resellers' }], hidden: !!p }, { name: 'title', label: 'Plan title', required: true }, { name: 'pricing_currency', label: 'Pricing currency', type: 'select', options: [{ value: 'IRT', label: 'Toman — fixed price' }, { value: 'USD', label: 'USD — live Wallex rate at checkout' }], required: true }, { name: 'price_irt', label: 'Price (Toman)', type: 'number', required: true, min: 0, showWhen: { name: 'pricing_currency', value: 'IRT' } }, { name: 'price_usd', label: 'Price (USD)', type: 'number', required: true, min: 0.01, step: 0.01, placeholder: 'Example: 4.99', showWhen: { name: 'pricing_currency', value: 'USD' } }, { name: 'volume_gb', label: 'Volume GB', type: 'number', required: true }, { name: 'reseller_validity_days', label: 'Validity days', type: 'number', required: true }, { name: 'server_id', label: 'Select server', type: 'select', options: serverOptionsList, required: true, full: true }] }; }
function paymentForm(serverOptionsList: any[], p?: PaymentItem): ModalForm { return { title: p ? 'Edit Payment' : 'Add Payment', action: p ? `/admin/payments/${p.id}/edit` : '/admin/payments/add', defaults: p ? { ...p, reviewer_telegram_id: p.reviewer_telegram_id || 0, show_for: p.server_type === 'reseller' ? 'reseller' : 'public' } : { show_for: 'public', server_id: 0, reviewer_telegram_id: 0 }, fields: [{ name: 'card_number', label: 'Card / account number', required: true }, { name: 'owner_name', label: 'Owner name', required: true }, { name: 'reviewer_telegram_id', label: 'Server owner / receipt reviewer Telegram ID (0 = main admins)', type: 'number', required: true, min: 0, full: true }, { name: 'show_for', label: 'Where to show', type: 'select', options: [{ value: 'public', label: 'Public' }, { value: 'reseller', label: 'Reseller' }] }, { name: 'server_id', label: 'Server for public payment', type: 'select', options: serverOptionsList, full: true }] }; }
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

function resellerForm(r?: ResellerItem, servers: ServerItem[] = []): ModalForm {
  const expiryDate = r?.expires_at ? String(r.expires_at).slice(0, 10) : '';
  const inboundOptionsByServer: Record<string, { value: string | number; label: string }[]> = {};
  for (const server of servers) {
    const rows = server.inbounds?.length ? server.inbounds : (server.inbound_ids || []).map((raw: any) => ({ id: Number(typeof raw === 'object' ? raw.id : raw), remark: '', protocol: '' }));
    inboundOptionsByServer[String(server.id)] = rows
      .filter((row: any) => Number(row.id) > 0 && row.enable !== false)
      .map((row: any) => ({ value: Number(row.id), label: `#${Number(row.id)} · ${row.remark || `Inbound ${Number(row.id)}`}${row.protocol ? ` (${row.protocol})` : ''}` }));
  }
  const groupOptionsByServer: Record<string, { value: string | number; label: string }[]> = {};
  for (const server of servers) {
    groupOptionsByServer[String(server.id)] = [
      { value: '', label: 'No client group' },
      ...(server.client_groups || []).map((group) => ({ value: group.name, label: group.client_count == null ? group.name : `${group.name} (${group.client_count} clients)` })),
    ];
  }
  if (r?.server_id && r.group_name) {
    const key = String(r.server_id);
    const options = groupOptionsByServer[key] || [{ value: '', label: 'No client group' }];
    if (!options.some((option) => String(option.value) === r.group_name)) {
      options.push({ value: r.group_name, label: `${r.group_name} (current — refresh groups if unavailable)` });
    }
    groupOptionsByServer[key] = options;
  }
  const resellerServers = servers.filter((server) => server.scope === 'reseller' || server.scope === 'all' || (r?.server_id && server.id === r.server_id));
  const defaults = r ? { total_gb: Math.round(r.total_bytes / 1024 ** 3), expires_at: expiryDate, server_id: r.server_id || 0, inbound_mode: r.inbound_mode || 'automatic', inbound_ids: r.inbound_ids || [], group_name: r.group_name || '' } : { total_gb: 0, days: 30 };
  return {
    title: r ? 'Edit Reseller' : 'Add Reseller',
    action: r ? `/admin/resellers/${r.id}/edit` : '/admin/resellers/add',
    defaults,
    fields: r ? [
      { name: 'total_gb', label: 'Total GB', type: 'number', required: true },
      { name: 'expires_at', label: 'Expiry date', type: 'date', required: false, full: true },
      { name: 'server_id', label: 'Assigned reseller server', type: 'select', options: serverOptions(resellerServers), full: true },
      { name: 'group_name', label: 'Sanaei client group for new reseller configurations', type: 'select', optionsBy: { name: 'server_id', map: groupOptionsByServer }, full: true, showWhen: { name: '__selected_server_type', value: 'xui' } },
      { name: 'inbound_mode', label: 'Reseller inbound mode', type: 'select', options: [{ value: 'automatic', label: 'Automatic — use all active server inbounds' }, { value: 'manual', label: 'Manual — restrict this reseller to selected inbounds' }], required: true, full: true, showWhen: { name: '__selected_server_type', value: 'xui' } },
      { name: 'inbound_ids', label: 'Allowed inbounds for this reseller', type: 'multiselect', optionsBy: { name: 'server_id', map: inboundOptionsByServer }, required: true, full: true, showWhenAll: [{ name: '__selected_server_type', value: 'xui' }, { name: 'inbound_mode', value: 'manual' }] }
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
function serviceTypeForm(s?: ServiceTypeItem): ModalForm { return { title: s ? 'Edit Service Type' : 'Add Service Type', action: s ? '/admin/service-types/edit' : '/admin/service-types/add', defaults: s ? { key: s.key, name: s.value, server_type: s.server_type_mode === 'manual' ? (s.server_type || 'xui') : 'auto' } : { server_type: 'auto' }, fields: [...(s ? [{ name: 'key', label: 'Key', type: 'text' as const, hidden: true }] : []), { name: 'name', label: 'Service name', required: true, full: true }, { name: 'server_type', label: 'Backend provider', type: 'select', required: true, full: true, options: [{ value: 'auto', label: 'Auto detect — compatible with existing types' }, { value: 'xui', label: 'X-UI / 3x-ui / Sanaei' }, { value: 'pasarguard', label: 'PasarGuard' }, { value: 'mikrotik', label: 'MikroTik / OpenVPN / L2TP' }] }] }; }
function settingsWebsiteForm(map: Record<string, string>): ModalForm {
  return {
    title: 'Website & SSL — Edit Setup', action: '/admin/settings/website',
    defaults: {
      domain: map.web_domain || '',
      web_path: map.web_path || 'dbot',
      username: map.web_admin_username || 'admin',
      password: '',
      token_timeout: map.web_token_timeout_minutes || '30',
    },
    fields: [
      { name: 'domain', label: 'Domain' },
      { name: 'web_path', label: 'Web Path', required: true, placeholder: 'dbot-a1b2c3d4' },
      { name: 'username', label: 'Current Web Admin Username', required: true },
      { name: 'password', label: 'New password — leave empty to keep current', type: 'password' },
      { name: 'token_timeout', label: 'Session timeout (minutes)', type: 'number', required: true },
    ],
  };
}

function openvpnProfileForm(serverOptionsList: any[], p?: OpenVPNProfileItem): ModalForm { return { title: p ? 'Edit OpenVPN Profile' : 'Add OpenVPN Profile', action: p ? `/admin/openvpn-profiles/${p.id}/edit` : '/admin/openvpn-profiles/add', defaults: p || { server_id: 0, file_name: 'profile.ovpn' }, fields: [{ name: 'name', label: 'Profile name', required: true }, { name: 'server_id', label: 'Bind to MikroTik / Custom server', type: 'select', options: serverOptionsList }, { name: 'file_name', label: 'File name', required: true }, { name: 'file', label: 'Upload .ovpn file', type: 'file', placeholder: '.ovpn', full: true }, { name: 'content', label: 'OVPN content', type: 'textarea', required: !p, full: true, placeholder: 'Paste .ovpn file content here or upload a file above' }] }; }
function backupForm(): ModalForm { return { title: 'Backup Settings', action: '/admin/backup/save', defaults: { channel: '@dbot_backup_channel', time: '03:00' }, fields: [{ name: 'channel', label: 'Backup channel', required: true }, { name: 'time', label: 'Backup time', type: 'time', required: true }] }; }

function SkeletonGrid() { return <div className="cards4"><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div>; }
function EmptyState({ message }: { message: string }) { return <div className="empty">{message}</div>; }
function EmptyInline() { return <div className="muted">No items found.</div>; }
