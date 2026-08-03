import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.stylesheets = []
        self.scripts = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.stylesheets.append(attrs.get("href"))
        if tag == "script" and attrs.get("src"):
            self.scripts.append(attrs.get("src"))

    def handle_data(self, data):
        self.text.append(data)


class StaticSiteContractTests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.parser = PageParser()
        self.parser.feed(self.html)

    def test_page_uses_local_assets_and_has_required_sections(self):
        self.assertEqual(self.parser.stylesheets, ["assets/styles.css"])
        self.assertEqual(self.parser.scripts, ["assets/app.js"])
        for section_id in ("status", "overview", "category-grid", "methodology", "chart-drawer"):
            self.assertIn(section_id, self.parser.ids)

    def test_page_contains_non_advice_disclaimer(self):
        text = " ".join(self.parser.text)
        self.assertIn("仅供估值观察与学习，不构成任何投资建议", text)

    def test_frontend_fetches_only_published_local_snapshot(self):
        script = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
        fetches = re.findall(r"fetch\(\s*['\"]([^'\"]+)", script)
        self.assertEqual(fetches, ["data/valuations.json"])
        self.assertNotIn("api.jiucaishuo.com", script)

    def test_seed_snapshot_covers_every_required_category(self):
        data = json.loads((ROOT / "data" / "valuations.json").read_text(encoding="utf-8"))
        categories = {item["category"] for item in data["indices"]}
        self.assertTrue(
            {"医药行业", "创新药", "CXO", "医疗器械", "医疗服务", "生物疫苗", "中药", "医药商业"}
            <= categories
        )
        self.assertEqual(data["schema_version"], 1)
        self.assertTrue(all(item["freshness"] in {"current", "stale", "unavailable"} for item in data["indices"]))


class WorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (ROOT / ".github" / "workflows" / "update-and-deploy.yml").read_text(encoding="utf-8")

    def test_workflow_supports_schedule_manual_run_and_pages_permissions(self):
        for required in ("schedule:", "workflow_dispatch:", "contents: write", "pages: write", "id-token: write"):
            self.assertIn(required, self.workflow)
        self.assertIn("30 10 * * 1-5", self.workflow)

    def test_tests_run_before_update_and_pages_deployment(self):
        test_pos = self.workflow.index("python -m unittest discover")
        update_pos = self.workflow.index("python scripts/update_data.py")
        upload_pos = self.workflow.index("actions/upload-pages-artifact@")
        deploy_pos = self.workflow.index("actions/deploy-pages@")
        self.assertLess(test_pos, update_pos)
        self.assertLess(update_pos, upload_pos)
        self.assertLess(upload_pos, deploy_pos)

    def test_workflow_exposes_diagnostic_summary_counts(self):
        self.assertIn("current=", self.workflow)
        self.assertIn("stale=", self.workflow)
        self.assertIn("unavailable=", self.workflow)


if __name__ == "__main__":
    unittest.main()
