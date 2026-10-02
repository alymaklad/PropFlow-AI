"""Data protection operations (task 4.1): erase one contact, and age out personal data.

PropFlow's ledger keeps raw inquiries for audit. These operations remove personal data while
keeping what the reports need (timestamps, statuses, scores, actions). Odoo is the system of
record for leads: erasure returns the affected Odoo lead ids for an Odoo administrator to
handle, because the integration user cannot delete leads (by design).

An opt-out is kept after erasure as a minimal suppression record (the contact key and the
fact that they opted out); deleting it would allow PropFlow to email them again.
"""

import re

import psycopg

from app.normalize import normalize_email, normalize_phone

ERASED = '{"erased": true}'


def contact_keys(contact: str) -> tuple[str | None, str | None]:
    email = normalize_email(contact)
    phone = None if email else normalize_phone(contact)
    return email, phone


def erase_contact(conn: psycopg.Connection, contact: str) -> dict:
    email, phone = contact_keys(contact)
    if not email and not phone:
        raise ValueError("not a valid email address or phone number")
    keys = [k for k in (email, phone) if k]
    digits = re.sub(r"\D", "", phone)[-9:] if phone else None  # raw payloads vary in format
    with conn.transaction():
        events = conn.execute(
            """
            SELECT id, correlation_id, odoo_lead_id FROM intake_events
             WHERE (%(email)s::text IS NOT NULL AND (lower(raw_payload->>'email') = %(email)s
                                                 OR lower(raw_payload->>'from') = %(email)s))
                OR (%(digits)s::text IS NOT NULL
                    AND regexp_replace(coalesce(raw_payload->>'phone', ''), '\\D', '', 'g')
                        LIKE '%%' || %(digits)s)
            """, {"email": email, "digits": digits}).fetchall()
        event_ids = [e[0] for e in events]
        cids = [str(e[1]) for e in events]
        conn.execute("UPDATE intake_events SET raw_payload = %s::jsonb, error = NULL"
                     " WHERE id = ANY(%s)", (ERASED, event_ids))
        conn.execute("UPDATE qualifications SET raw_output = NULL, validated_output = NULL"
                     " WHERE event_id = ANY(%s)", (event_ids,))
        scrubbed = conn.execute(
            "UPDATE outbound_messages SET to_address = NULL WHERE lower(to_address) = ANY(%s)"
            " OR lead_ref = ANY(%s) RETURNING id", (keys, cids)).fetchall()
        sequences = conn.execute(
            "DELETE FROM followup_sequences WHERE lower(to_email) = ANY(%s) OR contact_keys && %s"
            " OR correlation_id::text = ANY(%s) RETURNING id", (keys, keys, cids)).fetchall()
        conn.execute("DELETE FROM consents WHERE contact_key = ANY(%s) AND status = 'opted_in'",
                     (keys,))
        suppressed = conn.execute("SELECT count(*) FROM consents WHERE contact_key = ANY(%s)",
                                  (keys,)).fetchone()[0]
    return {
        "events_erased": len(event_ids),
        "messages_scrubbed": len(scrubbed),
        "sequences_deleted": len(sequences),
        "opt_out_kept": suppressed > 0,
        "odoo_lead_ids": sorted({e[2] for e in events if e[2]}),
        "note": "Delete or anonymise the listed Odoo leads in Odoo (the integration user "
                "cannot delete leads). n8n execution history is pruned automatically.",
    }


def apply_retention(conn: psycopg.Connection, older_than_days: int) -> dict:
    """Anonymise personal data older than the cut-off; counts used by reports are kept."""
    if older_than_days < 7:
        raise ValueError("retention must be at least 7 days")
    cutoff = f"now() - make_interval(days => {int(older_than_days)})"
    with conn.transaction():
        events = conn.execute(
            f"UPDATE intake_events SET raw_payload = %s::jsonb, error = NULL"
            f" WHERE received_at < {cutoff} AND raw_payload <> %s::jsonb RETURNING id",
            (ERASED, ERASED)).fetchall()
        quals = conn.execute(
            f"UPDATE qualifications SET raw_output = NULL, validated_output = NULL"
            f" WHERE created_at < {cutoff} AND (raw_output IS NOT NULL"
            f" OR validated_output IS NOT NULL) RETURNING id").fetchall()
        messages = conn.execute(
            f"UPDATE outbound_messages SET to_address = NULL WHERE created_at < {cutoff}"
            f" AND to_address IS NOT NULL RETURNING id").fetchall()
        sequences = conn.execute(
            f"DELETE FROM followup_sequences WHERE status <> 'active' AND updated_at < {cutoff}"
            f" RETURNING id").fetchall()
        dead = conn.execute(
            f"UPDATE dead_letters SET payload = '{{}}'::jsonb WHERE created_at < {cutoff}"
            f" AND payload <> '{{}}'::jsonb RETURNING id").fetchall()
    return {"older_than_days": older_than_days, "events_anonymised": len(events),
            "qualifications_cleared": len(quals), "messages_scrubbed": len(messages),
            "sequences_deleted": len(sequences), "dead_letters_cleared": len(dead)}
