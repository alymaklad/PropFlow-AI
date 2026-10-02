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
