"""In-memory stand-in for OdooClient covering the calls app.crm and app.assignment make."""

import itertools

from app.odoo_client import OdooDuplicateError


def _matches(record: dict, domain: list) -> bool:
    """Evaluate the subset of Odoo domain syntax we use: '|' prefixes, '=' and '<'."""
    stack: list[bool] = []
    for token in reversed(domain):
        if token == "|":
            stack.append(stack.pop() or stack.pop())
        else:
            field, op, value = token
            actual = record.get(field)
            stack.append(actual == value if op == "=" else
                         actual is not None and actual < value)
    return all(stack)


class FakeOdoo:
    def __init__(self, members=(10, 11, 12), team_id=1):
        self.team_id = team_id
        self.members = list(members)
        self.leads: dict[int, dict] = {}
        self.notes: list[tuple[int, str]] = []
        self.activities: dict[tuple[int, str], dict] = {}
        self.lose_next_create_response = False
        self._ids = itertools.count(1)
        self._clock = itertools.count(1)

    def search_read(self, model, domain, fields, limit=None, order=None, context=None):
        if model == "crm.team":
            return [{"id": self.team_id}]
        if model == "crm.team.member":
            return [{"user_id": [uid, f"Rep {uid}"]} for uid in self.members]
        assert model == "crm.lead", model
        found = [lead for lead in self.leads.values() if _matches(lead, domain)
                 and (lead["active"] or (context or {}).get("active_test") is False)]
        if order == "create_date desc":
            found.sort(key=lambda r: r["create_date"], reverse=True)
        return [{f: r.get(f) for f in fields} for r in found[:limit]]

    def execute(self, model, method, *args, **kwargs):
        assert model == "crm.lead", model
        if method == "create":
            values = args[0]
            if isinstance(values, list):  # vals_list form, like Odoo 17: returns a list of ids
                return [self._create(v) for v in values]
            return self._create(values)
        if method == "write":
            ids, values = args
            for lead_id in ids:
                self.leads[lead_id].update(self._store(values))
            return True
        if method == "propflow_post_note":
            (lead_id,), body = args
            self.notes.append((lead_id, body))
            return len(self.notes)
        if method == "propflow_schedule_activity":
            (lead_id,), summary, user_id, deadline, note = args
            key = (lead_id, summary)
            self.activities.setdefault(key, {"id": len(self.activities) + 1, "user_id": user_id,
                                             "deadline": deadline})
            return self.activities[key]["id"]
        raise NotImplementedError(method)

    def _store(self, values: dict) -> dict:
        stored = dict(values)
        for key in ("user_id", "team_id"):
            if key in stored:
                stored[key] = [stored[key], "x"] if stored[key] else False
        return stored

    def _create(self, values: dict) -> int:
        cid = values.get("propflow_correlation_id")
        if cid and any(lead.get("propflow_correlation_id") == cid for lead in self.leads.values()):
            raise OdooDuplicateError("PropFlow correlation ID already exists")
        lead_id = next(self._ids)
        record = {"id": lead_id, "active": True, "probability": 10,
                  "create_date": next(self._clock), **self._store(values)}
        record["phone_sanitized"] = record.get("phone") or None
        record["email_normalized"] = (record.get("email_from") or "").lower() or None
        self.leads[lead_id] = record
        if self.lose_next_create_response:
            # Odoo created the lead but the response was lost; the client's retry then hits
            # the unique constraint.
            self.lose_next_create_response = False
            raise OdooDuplicateError("PropFlow correlation ID already exists")
        return lead_id
