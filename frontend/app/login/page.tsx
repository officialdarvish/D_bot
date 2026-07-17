import { LockKeyhole, ShieldCheck } from 'lucide-react';

export default function LoginPage() {
  return (
    <main className="login-state login-page-v2">
      <form className="card login-card login-form-v2" method="post" action="/login">
        <div className="logo-mark mx-auto mb-4"><span>D</span></div>
        <div className="login-title"><ShieldCheck size={22} /> D BOT Owner Login</div>
        <p className="muted">Secure owner access</p>
        <input type="hidden" name="next_url" value="/admin" />
        <label className="form-field full"><span>Username</span><input name="username" autoComplete="username" required placeholder="Enter owner username" /></label>
        <label className="form-field full"><span>Password</span><input name="password" type="password" autoComplete="current-password" required placeholder="Enter password" /></label>
        <button className="btn primary" type="submit"><LockKeyhole size={16} /> Login</button>
      </form>
    </main>
  );
}
