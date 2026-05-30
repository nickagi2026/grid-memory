"""Tests for the enterprise tenant model."""

import os
import tempfile
import unittest
from grid_memory.enterprise.tenant import TenantManager


class TestTenantManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "tenants.db")
        self.tm = TenantManager(db_path=self.db_path, base_dir=os.path.join(self.tmpdir, "ws"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_tenant(self):
        r = self.tm.create_tenant("Acme Corp", "acme.com", "enterprise")
        self.assertIn("tenant_id", r)
        self.assertIn("workspace_id", r)
        self.assertEqual(r["name"], "Acme Corp")

    def test_get_tenant(self):
        r = self.tm.create_tenant("Beta Inc")
        t = self.tm.get_tenant(r["tenant_id"])
        self.assertIsNotNone(t)
        self.assertEqual(t["name"], "Beta Inc")
        self.assertIn("workspaces", t)

    def test_list_tenants(self):
        self.tm.create_tenant("Company A")
        self.tm.create_tenant("Company B")
        tenants = self.tm.list_tenants()
        self.assertGreaterEqual(len(tenants), 2)

    def test_update_tenant(self):
        r = self.tm.create_tenant("Old Name")
        self.tm.update_tenant(r["tenant_id"], name="New Name", plan="enterprise")
        t = self.tm.get_tenant(r["tenant_id"])
        self.assertEqual(t["name"], "New Name")
        self.assertEqual(t["plan"], "enterprise")

    def test_create_workspace(self):
        tr = self.tm.create_tenant("Test Co")
        wr = self.tm.create_workspace(tr["tenant_id"], "prod-env", "sqlite", 90)
        self.assertEqual(wr["name"], "prod-env")
        self.assertIn("workspace_id", wr)

    def test_get_workspace(self):
        tr = self.tm.create_tenant("Test Co")
        wr = self.tm.create_workspace(tr["tenant_id"], "staging")
        ws = self.tm.get_workspace(wr["workspace_id"])
        self.assertIsNotNone(ws)
        self.assertEqual(ws["name"], "staging")

    def test_create_user(self):
        tr = self.tm.create_tenant("Test Co")
        ur = self.tm.create_user(tr["tenant_id"], "alice@test.com", "Alice", "architect")
        self.assertEqual(ur["email"], "alice@test.com")
        self.assertEqual(ur["role"], "architect")

    def test_get_users(self):
        tr = self.tm.create_tenant("Test Co")
        self.tm.create_user(tr["tenant_id"], "a@t.com", "A", "viewer")
        self.tm.create_user(tr["tenant_id"], "b@t.com", "B", "admin")
        users = self.tm.get_users(tr["tenant_id"])
        self.assertGreaterEqual(len(users), 2)

    def test_update_user_role(self):
        tr = self.tm.create_tenant("Test Co")
        ur = self.tm.create_user(tr["tenant_id"], "test@t.com", "Test", "viewer")
        self.tm.update_user_role(ur["user_id"], "executive")
        users = self.tm.get_users(tr["tenant_id"])
        updated = [u for u in users if u["id"] == ur["user_id"]][0]
        self.assertEqual(updated["role"], "executive")

    def test_retention_policy(self):
        tr = self.tm.create_tenant("Test Co")
        wr = self.tm.create_workspace(tr["tenant_id"], "main")
        self.tm.set_retention_policy(wr["workspace_id"], 90)
        ws = self.tm.get_workspace(wr["workspace_id"])
        self.assertEqual(ws["retention_days"], 90)

    def test_encryption_toggle(self):
        tr = self.tm.create_tenant("Test Co")
        wr = self.tm.create_workspace(tr["tenant_id"], "secure")
        self.tm.set_encryption(wr["workspace_id"], True)
        ws = self.tm.get_workspace(wr["workspace_id"])
        self.assertEqual(ws["encryption_enabled"], 1)

    def test_usage_logging(self):
        tr = self.tm.create_tenant("Test Co")
        self.tm.log_usage(tr["tenant_id"], api_calls=10, entries_written=5, storage_bytes=1024)
        self.tm.log_usage(tr["tenant_id"], api_calls=5, entries_written=2)
        usage = self.tm.get_usage(tr["tenant_id"], days=30)
        self.assertGreaterEqual(usage["total_api_calls"], 15)
        self.assertGreaterEqual(usage["total_entries_written"], 7)

    def test_admin_summary(self):
        self.tm.create_tenant("T1")
        self.tm.create_tenant("T2")
        summary = self.tm.admin_summary()
        self.assertGreaterEqual(summary["total_tenants"], 2)

    def test_invalid_role_rejected(self):
        tr = self.tm.create_tenant("Test")
        ur = self.tm.create_user(tr["tenant_id"], "x@x.com", "X", "superadmin")
        self.assertEqual(ur["role"], "viewer")  # defaulted

    def test_tenant_usage_zero_initially(self):
        tr = self.tm.create_tenant("Fresh Co")
        t = self.tm.get_tenant(tr["tenant_id"])
        self.assertEqual(t["total_api_calls"], 0)

    def test_create_multiple_workspaces(self):
        tr = self.tm.create_tenant("Multi WS")
        self.tm.create_workspace(tr["tenant_id"], "dev")
        self.tm.create_workspace(tr["tenant_id"], "prod")
        t = self.tm.get_tenant(tr["tenant_id"])
        self.assertEqual(len(t["workspaces"]), 3)  # 1 default + 2 new


if __name__ == "__main__":
    unittest.main()
