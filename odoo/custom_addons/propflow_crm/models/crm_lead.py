from odoo import fields, models
from odoo.tools import plaintext2html

PROPERTY_TYPES = [
    ("apartment", "Apartment"),
    ("villa", "Villa"),
    ("townhouse", "Townhouse"),
    ("duplex", "Duplex"),
    ("penthouse", "Penthouse"),
    ("studio", "Studio"),
    ("chalet", "Chalet"),
    ("land", "Land"),
    ("commercial", "Commercial"),
    ("office", "Office"),
]
# Selection rather than Integer: Odoo reads an empty integer back as 0, which would make
# "unknown" indistinguishable from "studio".
BEDROOMS = [("0", "Studio"), ("1", "1"), ("2", "2"), ("3", "3"), ("4", "4"), ("5", "5"),
            ("6", "6+")]


class CrmLead(models.Model):
    _inherit = "crm.lead"

    propflow_correlation_id = fields.Char(
        "Correlation ID", copy=False, index=True, readonly=True,
        help="Set by the PropFlow intake workflow; ties this lead to its event ledger entry.",
    )
    propflow_source = fields.Selection(
        [("form", "Web form"), ("email", "Email"), ("whatsapp", "WhatsApp"),
         ("manual", "Manual")],
        "Intake source", readonly=True,
    )
    propflow_original_message = fields.Text("Original inquiry", readonly=True)
    propflow_property_type = fields.Selection(PROPERTY_TYPES, "Property type")
    propflow_location = fields.Char("Location")
    propflow_bedrooms = fields.Selection(BEDROOMS, "Bedrooms")
    propflow_budget_min = fields.Float("Budget from", digits=(16, 0))
    propflow_budget_max = fields.Float("Budget up to", digits=(16, 0))
    propflow_currency = fields.Char("Budget currency", size=3)
    propflow_delivery_pref = fields.Selection(
        [("ready", "Ready"), ("under_construction", "Under construction"),
         ("off_plan", "Off plan"), ("any", "Any")],
        "Delivery preference",
    )
    propflow_timeline_months = fields.Integer("Purchase timeline (months)")
    propflow_score = fields.Integer("PropFlow score", readonly=True)
    propflow_priority = fields.Selection(
        [("high", "High"), ("standard", "Standard"), ("nurture", "Nurture")],
        "PropFlow priority", readonly=True, index=True,
    )
    propflow_score_explanation = fields.Text("Score explanation", readonly=True)
    propflow_rules_version = fields.Char("Scoring rules version", readonly=True)
    propflow_exception_status = fields.Selection(
        [("none", "None"), ("handoff", "Handed off to salesperson"),
         ("sync_error", "Sync error")],
        "Exception status", default="none", index=True,
    )
    propflow_automation = fields.Selection(
        [("active", "Active"), ("paused", "Paused")], "PropFlow automation", default="active",
        index=True,
        help="Pause to stop PropFlow's automatic customer follow-ups for this lead.",
    )
    propflow_last_contact = fields.Datetime("Last contact")
    propflow_next_followup = fields.Date("Next follow-up")

    _sql_constraints = [
        ("propflow_correlation_id_unique", "unique(propflow_correlation_id)",
         "A lead with this PropFlow correlation ID already exists."),
    ]

    # --- RPC helpers for the PropFlow integration -------------------------------------------
    # Public so they can be called over JSON-RPC; each checks write access on the lead first.

    def propflow_schedule_activity(self, summary, user_id, date_deadline, note=False):
        """Schedule a To-Do for `user_id` unless an open activity with the same summary
        already exists on the lead, and set the lead's next follow-up date. Returns the
        activity id.

        Safe to retry and to call concurrently: writing the lead first takes its row lock, so a
        parallel call fails with a serialization error, which Odoo retries automatically; the
        retry then finds the activity created by the first call."""
        self.ensure_one()
        self.check_access_rights("write")
        self.check_access_rule("write")
        self.write({"propflow_next_followup": date_deadline})
        self.flush_recordset(["propflow_next_followup"])
        existing = self.activity_ids.filtered(lambda a: a.summary == summary)
        if existing:
            return existing[0].id
        activity = self.activity_schedule(
            "mail.mail_activity_data_todo",
            date_deadline=date_deadline,
            summary=summary,
            note=note or "",
            user_id=user_id,
        )
        return activity.id

    def propflow_post_note(self, body):
        """Post an internal note. `body` is plain text: it is HTML-escaped (so customer text
        cannot inject markup) and line breaks are kept. Returns the message id."""
        self.ensure_one()
        self.check_access_rights("write")
        self.check_access_rule("write")
        message = self.message_post(body=plaintext2html(body), message_type="comment",
                                    subtype_xmlid="mail.mt_note")
        return message.id
