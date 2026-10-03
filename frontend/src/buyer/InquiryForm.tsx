import { useEffect, useRef, useState } from "react";
import { type FieldError, sendInquiry } from "../api";
import { type Search, describeSearch } from "./SentenceBuilder";

const TIMELINES = [
  { value: "", text: "Not sure yet" },
  { value: "immediately", text: "As soon as possible" },
  { value: "within_3_months", text: "Within 3 months" },
  { value: "3_6_months", text: "In 3 to 6 months" },
  { value: "6_12_months", text: "In 6 to 12 months" },
  { value: "over_12_months", text: "In more than a year" },
];
const STAGES = [
  { value: "", text: "Prefer not to say" },
  { value: "just_browsing", text: "Just browsing" },
  { value: "comparing_options", text: "Comparing options" },
  { value: "ready_to_buy", text: "Ready to buy" },
];

type Props = { search: Search; message: string; onMessageChange: (m: string) => void; demoDelivery?: boolean };

export function InquiryForm({ search, message, onMessageChange, demoDelivery = false }: Props) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [timeline, setTimeline] = useState("");
  const [stage, setStage] = useState("");
  const [website, setWebsite] = useState("");
  const [submissionId, setSubmissionId] = useState(() => crypto.randomUUID());
  const [sending, setSending] = useState(false);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [sent, setSent] = useState<string | null>(null);
  const doneRef = useRef<HTMLDivElement>(null);

  useEffect(() => { if (sent) doneRef.current?.focus(); }, [sent]);

  const errorFor = (field: string) => errors.find((e) => e.field === field)?.message;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSending(true);
    setErrors([]);
    setProblem(null);
    const result = await sendInquiry({
      submission_id: submissionId,
      name: name.trim(),
      email: email.trim() || undefined,
      phone: phone.trim() || undefined,
      property_type: search.type !== "any" ? search.type : undefined,
      location: search.location !== "any" ? search.location : undefined,
      bedrooms: search.bedrooms !== "any" ? Number(search.bedrooms) : undefined,
      budget_max: search.budget !== "any" ? Number(search.budget) : undefined,
      timeline: timeline || undefined,
      purchase_stage: stage || undefined,
      message: message.trim() || undefined,
      website: website || undefined,
    });
    setSending(false);
    if (result.ok) setSent(result.reference);
    else {
      setErrors(result.errors);
      setProblem(result.message ?? null);
    }
  }

  if (sent) {
    return (
      <div className="inquiry-done" ref={doneRef} tabIndex={-1} role="status">
        <h2>Sent. Check your inbox in a few minutes.</h2>
        <p>
          You'll get matching listings or a quick question by email. Your advisor follows up during
          business hours, Sunday to Thursday, 9:00 to 17:00 Cairo time.
        </p>
        <p className="inquiry-ref">Reference <span className="num">{sent}</span></p>
        <button type="button" className="btn btn-quiet" onClick={() => { setSent(null); setSubmissionId(crypto.randomUUID()); onMessageChange(""); }}>
          Send another inquiry
        </button>
      </div>
    );
  }

  return (
    <form className="inquiry-form" onSubmit={submit} noValidate>
      <p className="inquiry-summary">
        We'll send your search with it: <strong>{describeSearch(search)}</strong>. Change it in the sentence above.
      </p>
      <div className="field">
        <label htmlFor="f-name">Your name</label>
        <input id="f-name" required autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="field-pair">
        <div className="field">
          <label htmlFor="f-email">Email</label>
          <input id="f-email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)}
            aria-invalid={!!errorFor("email")} aria-describedby="f-contact-hint f-email-error" />
          {errorFor("email") && <p className="field-error" id="f-email-error">{errorFor("email")}</p>}
        </div>
        <div className="field">
          <label htmlFor="f-phone">Phone</label>
          <input id="f-phone" type="tel" autoComplete="tel" inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)}
            aria-invalid={!!errorFor("phone")} aria-describedby="f-contact-hint f-phone-error" />
          {errorFor("phone") && <p className="field-error" id="f-phone-error">{errorFor("phone")}</p>}
        </div>
      </div>
      <p className="field-hint" id="f-contact-hint">An email address or a phone number is enough. We reply by email when we can.</p>
      <div className="field-pair">
        <div className="field">
          <label htmlFor="f-timeline">When do you plan to buy?</label>
          <select id="f-timeline" value={timeline} onChange={(e) => setTimeline(e.target.value)}>
            {TIMELINES.map((t) => <option key={t.value} value={t.value}>{t.text}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-stage">Where are you in your search?</label>
          <select id="f-stage" value={stage} onChange={(e) => setStage(e.target.value)}>
            {STAGES.map((s) => <option key={s.value} value={s.value}>{s.text}</option>)}
          </select>
        </div>
      </div>
      <div className="field">
        <label htmlFor="f-message">Anything else an advisor should know?</label>
        <textarea id="f-message" rows={4} value={message} onChange={(e) => onMessageChange(e.target.value)}
          placeholder="A garden, a school nearby, a payment plan..." aria-invalid={!!errorFor("message")}
          aria-describedby={errorFor("message") ? "f-message-error" : undefined} />
        {errorFor("message") && <p className="field-error" id="f-message-error">{errorFor("message")}</p>}
      </div>
      <div className="field honeypot" aria-hidden="true">
        <label htmlFor="f-website">Leave this empty</label>
        <input id="f-website" tabIndex={-1} autoComplete="off" value={website} onChange={(e) => setWebsite(e.target.value)} />
      </div>
      {problem && <p className="form-problem" role="alert">{problem}</p>}
      <button type="submit" className="btn" disabled={sending}>{sending ? "Sending..." : "Send to an advisor"}</button>
      <p className="field-hint">
        {demoDelivery
          ? "We use your details only to answer this inquiry: one email, no reminders, no mailing list."
          : "We use your details only to answer this inquiry. Reply STOP to any email and we won't contact you again."}
      </p>
    </form>
  );
}
