import os
import time
import unittest
from pathlib import Path

from src.arxiv_zotero import (
    ArxivPaper,
    ZoteroClient,
    normalize_arxiv_id,
    normalize_arxiv_id_from_text,
    new_write_token,
    parse_arxiv_atom,
)


ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.12345v2</id>
    <updated>2026-09-01T12:00:00Z</updated>
    <published>2026-08-21T10:00:00Z</published>
    <title>  A   Test Paper </title>
    <summary>Test abstract.</summary>
    <author><name>Alice Smith</name></author>
    <author><name>Bob Jones</name></author>
    <link title="pdf" href="https://arxiv.org/pdf/2401.12345v2" type="application/pdf"/>
  </entry>
</feed>"""


class ParsingTests(unittest.TestCase):
    def test_normalizes_urls_and_versions(self):
        self.assertEqual(normalize_arxiv_id("https://arxiv.org/pdf/2401.12345v2.pdf"),
                         ("2401.12345", 2))
        self.assertEqual(normalize_arxiv_id("astro-ph/0601001"), ("astro-ph/0601001", None))

    def test_extracts_id_from_zotero_metadata(self):
        self.assertEqual(normalize_arxiv_id_from_text("arXiv: 2401.12345v3"),
                         ("2401.12345", 3))

    def test_parses_atom_and_month(self):
        paper = parse_arxiv_atom(ATOM)
        self.assertEqual(paper.versioned_id, "2401.12345v2")
        self.assertEqual(paper.month, "202608")
        self.assertEqual(paper.title, "A Test Paper")
        self.assertEqual(paper.authors, ["Alice Smith", "Bob Jones"])

    def test_write_token_meets_zotero_length_limit(self):
        token = new_write_token()
        self.assertEqual(len(token), 32)
        self.assertNotIn('-', token)


class FakeZotero(ZoteroClient):
    def __init__(self, existing=None):
        self.existing = existing
        self.created = []
        self.updated = []
        self.uploaded = []

    def ensure_target_collection(self, month):
        self.month = month
        return "MONTHKEY"

    def find_arxiv_item(self, _base_id):
        return self.existing

    def _create_item(self, data):
        self.created.append(data)
        return "NEWPARENT" if data["itemType"] != "attachment" else "NEWATTACH"

    def _update_parent(self, item, paper, collection_key):
        self.updated.append((item, paper, collection_key))
        return item["key"]

    def _label_existing_pdfs(self, *args):
        self.labelled = args

    def _upload_pdf(self, parent_key, paper, pdf_path):
        self.uploaded.append((parent_key, paper.version, pdf_path))
        return "ATTACH"


class ImportDecisionTests(unittest.TestCase):
    def setUp(self):
        self.paper = parse_arxiv_atom(ATOM)
        self.pdf = Path("/tmp/2401.12345v2.pdf")

    def test_creates_new_parent_and_attachment(self):
        client = FakeZotero()
        result = client.import_paper(self.paper, self.pdf)
        self.assertEqual(result["status"], "created")
        self.assertEqual(client.month, "202608")
        self.assertEqual(client.created[0]["collections"], ["MONTHKEY"])
        self.assertEqual(len(client.uploaded), 1)

    def test_skips_same_or_newer_version(self):
        existing = {"key": "OLD", "data": {"url": "https://arxiv.org/abs/2401.12345v2"}}
        client = FakeZotero(existing)
        result = client.import_paper(self.paper, self.pdf)
        self.assertEqual(result["status"], "skipped")
        self.assertFalse(client.uploaded)

    def test_updates_lower_version_and_preserves_parent(self):
        existing = {"key": "OLD", "data": {"url": "https://arxiv.org/abs/2401.12345v1"}}
        client = FakeZotero(existing)
        result = client.import_paper(self.paper, self.pdf)
        self.assertEqual(result["status"], "updated")
        self.assertEqual(result["item_key"], "OLD")
        self.assertEqual(client.labelled[1], 1)
        self.assertEqual(client.uploaded[0][0], "OLD")

    def test_unversioned_item_added_after_revision_is_current(self):
        existing = {"key": "OLD", "data": {
            "url": "https://arxiv.org/abs/2401.12345",
            "extra": "arXiv:2401.12345 [astro-ph.GA]",
            "dateAdded": "2026-09-02T00:00:00Z",
        }}
        self.assertEqual(ZoteroClient.item_arxiv_version(existing, self.paper), 2)


class WebAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["ARXIV_WEBUI_WRITE_TOKEN"] = "unit-test-password"
        import webui
        cls.webui = webui
        cls.client = webui.app.test_client()

    def tearDown(self):
        os.environ["ARXIV_WEBUI_WRITE_TOKEN"] = "unit-test-password"

    def test_password_and_two_hour_expiry(self):
        response = self.client.post("/api/zotero/auth", json={"password": "unit-test-password"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.client.get("/api/zotero/auth/status").json["authenticated"])
        with self.client.session_transaction() as state:
            state["zotero_authenticated_at"] = time.time() - 7201
        self.assertFalse(self.client.get("/api/zotero/auth/status").json["authenticated"])

    def test_password_change_invalidates_session(self):
        self.client.post("/api/zotero/auth", json={"password": "unit-test-password"})
        os.environ["ARXIV_WEBUI_WRITE_TOKEN"] = "changed-password"
        self.assertFalse(self.client.get("/api/zotero/auth/status").json["authenticated"])


if __name__ == "__main__":
    unittest.main()
