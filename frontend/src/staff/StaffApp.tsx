import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AuthError, staffFetch, staffToken } from "../api";
import { Dashboard } from "./Dashboard";
import "./staff.css";

export function StaffApp() {
  const [token, setToken] = useState<string | null>(() => staffToken.get());
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  useEffect(() => { document.title = "PropFlow staff"; }, []);

  async function signIn(event: React.FormEvent) {
    event.preventDefault();
    setChecking(true);
    setError(null);
    try {
      await staffFetch("/session", {}, draft.trim());
      staffToken.set(draft.trim());
      setToken(draft.trim());
    } catch (e) {
      setError(e instanceof AuthError ? "That token wasn't accepted. Check STAFF_TOKEN in the PropFlow .env file."
        : "The PropFlow service isn't reachable. Check that the stack is running.");
    } finally {
      setChecking(false);
    }
  }

  function signOut() {
    staffToken.clear();
    setToken(null);
    setDraft("");
  }

  if (token) return <Dashboard onSignOut={signOut} onAuthLost={signOut} />;

  return (
    <div className="staff-signin">
      <form onSubmit={signIn} className="signin-panel">
        <h1>PropFlow staff</h1>
        <p>Sign in with the staff token from the PropFlow configuration (STAFF_TOKEN).</p>
        <label htmlFor="s-token">Staff token</label>
        <input id="s-token" type="password" autoComplete="current-password" value={draft}
          onChange={(e) => setDraft(e.target.value)} aria-describedby={error ? "s-error" : undefined} />
        {error && <p className="signin-error" id="s-error" role="alert">{error}</p>}
        <button className="btn" type="submit" disabled={checking || !draft.trim()}>
          {checking ? "Checking..." : "Sign in"}
        </button>
        <Link to="/" className="signin-back">Back to the buyer site</Link>
      </form>
    </div>
  );
}
