from psycopg2 import IntegrityError

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install", "propflow")
class TestPropflowLead(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env["res.users"].with_context(no_reset_password=True)
        cls.integration = Users.create({
            "name": "Integration (test)",
            "login": "propflow-integration-test",
            "email": "propflow-integration-test@example.com",
            "groups_id": [(6, 0, [cls.env.ref("propflow_crm.group_propflow_integration").id])],
        })
        cls.rep = Users.create({
            "name": "Rep (test)",
            "login": "propflow-rep-test",
            "email": "propflow-rep-test@example.com",
            "groups_id": [(6, 0, [cls.env.ref("sales_team.group_sale_salesman").id])],
        })
        cls.reviewer = Users.create({
            "name": "Reviewer (test)",
            "login": "propflow-reviewer-test",
            "email": "propflow-reviewer-test@example.com",
            "groups_id": [(6, 0, [cls.env.ref("propflow_crm.group_propflow_reviewer").id])],
        })

    def _lead(self, **vals):
        return self.env["crm.lead"].with_user(self.integration).create(
            {"name": "Test lead", "type": "lead", **vals})

    def test_correlation_id_is_unique(self):
        self._lead(propflow_correlation_id="cid-1")
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"), self.cr.savepoint():
            self._lead(propflow_correlation_id="cid-1")

    def test_leads_without_correlation_id_are_allowed(self):
        self._lead()
        self._lead()

    def test_automation_defaults_to_active_and_can_be_paused(self):
        lead = self._lead(user_id=self.rep.id)  # reps edit their own leads
        self.assertEqual(lead.propflow_automation, "active")
        lead.with_user(self.rep).write({"propflow_automation": "paused"})
        self.assertEqual(lead.propflow_automation, "paused")

    def test_integration_can_create_read_write_but_not_delete(self):
        lead = self._lead(propflow_correlation_id="cid-2", propflow_bedrooms="0",
                          propflow_property_type="studio", user_id=self.rep.id)
        lead.write({"propflow_score": 70, "propflow_priority": "standard"})
        self.assertEqual(lead.read(["propflow_bedrooms"])[0]["propflow_bedrooms"], "0")
        with self.assertRaises(AccessError):
            lead.unlink()

    def test_integration_cannot_change_settings(self):
        with self.assertRaises(AccessError):
            self.env["res.config.settings"].with_user(self.integration).create({})

    def test_schedule_activity_is_idempotent(self):
        lead = self._lead(user_id=self.rep.id)
        deadline = fields.Date.today()
        first = lead.propflow_schedule_activity("Follow up", self.rep.id, deadline)
        again = lead.propflow_schedule_activity("Follow up", self.rep.id, deadline)
        self.assertEqual(first, again)
        activity = self.env["mail.activity"].browse(first)
        self.assertEqual(activity.user_id, self.rep)
        self.assertEqual(len(lead.activity_ids), 1)
        self.assertEqual(lead.propflow_next_followup, deadline)

    def test_post_note_escapes_html(self):
        lead = self._lead()
        message = self.env["mail.message"].browse(
            lead.propflow_post_note("<script>alert(1)</script> 3 bedrooms\nbudget 6M"))
        self.assertNotIn("<script>", message.body)
        self.assertIn("3 bedrooms", message.body)
        self.assertIn("<br>", message.body)

    def test_reviewer_can_read_leads_and_see_the_crm_menu(self):
        lead = self._lead(propflow_location="Maadi", user_id=self.rep.id)
        as_reviewer = lead.with_user(self.reviewer)
        self.assertEqual(as_reviewer.propflow_location, "Maadi")
        self.assertEqual(as_reviewer.user_id.name, "Rep (test)")
        menus = self.env["ir.ui.menu"].with_user(self.reviewer)._visible_menu_ids()
        self.assertIn(self.env.ref("crm.crm_menu_root").id, menus)
        self.assertIn(self.env.ref("crm.crm_menu_leads").id, menus)

    def test_reviewer_cannot_change_anything(self):
        lead = self._lead().with_user(self.reviewer)
        with self.assertRaises(AccessError):
            lead.write({"name": "changed"})
        with self.assertRaises(AccessError):
            self.env["crm.lead"].with_user(self.reviewer).create({"name": "new"})
        with self.assertRaises(AccessError):
            lead.unlink()
        with self.assertRaises(AccessError):
            lead.message_post(body="a note", message_type="comment")
        with self.assertRaises(AccessError):
            lead.activity_schedule("mail.mail_activity_data_todo", summary="call")
        with self.assertRaises(AccessError):
            self.env["res.partner"].with_user(self.reviewer).create({"name": "new contact"})

    def test_reviewer_form_has_no_action_buttons(self):
        View = self.env["crm.lead"]
        reviewer_arch = View.with_user(self.reviewer).get_views([(False, "form")])["views"]["form"]["arch"]
        rep_arch = View.with_user(self.rep).get_views([(False, "form")])["views"]["form"]["arch"]
        header = reviewer_arch.split("<header>")[1].split("</header>")[0]
        self.assertNotIn("<button", header)
        self.assertIn('name="stage_id"', header)
        self.assertIn("Convert to Opportunity", rep_arch)

    def test_handoff_reason_is_stored(self):
        lead = self._lead()
        lead.write({"propflow_exception_status": "handoff",
                    "propflow_handoff_reason": "The customer asked to speak to a person"})
        self.assertEqual(lead.propflow_handoff_reason, "The customer asked to speak to a person")

