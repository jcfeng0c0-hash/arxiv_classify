"""arXiv PDF 下载及 Zotero Desktop 10+ 导入。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin
from xml.etree import ElementTree

import requests

ARXIV_API_URL = "https://export.arxiv.org/api/query"
ZOTERO_BASE_URL = "http://127.0.0.1:23119/api"
ARXIV_ID_RE = re.compile(
    r"(?:(?:arxiv\.org)/(?:abs|pdf)/)?"
    r"(?P<base>(?:[a-z-]+(?:\.[A-Z]{2})?/\d{7}|\d{4}\.\d{4,5}))"
    r"(?:v(?P<version>\d+))?(?:\.pdf)?$", re.I)
TEXT_ID_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/|arXiv(?: ID)?:\s*|arXiv:\s*)"
    r"([\w.-]+/\d{7}|\d{4}\.\d{4,5})(?:v(\d+))?", re.I)
VERSION_RE = re.compile(
    r"(?:arXiv(?: ID)?:\s*)?([\w.-]+/\d{7}|\d{4}\.\d{4,5})v(\d+)", re.I)


class ImportError(RuntimeError):
    """可安全显示给用户的预期导入错误。"""


def new_write_token():
    """Zotero requires write tokens to contain 5-32 characters."""
    return uuid.uuid4().hex


@dataclass(frozen=True)
class ArxivPaper:
    base_id: str
    version: int
    title: str
    authors: list[str]
    abstract: str
    published: str
    updated: str
    abs_url: str
    pdf_url: str

    @property
    def versioned_id(self):
        return f"{self.base_id}v{self.version}"

    @property
    def month(self):
        match = re.match(r"(\d{4})-(\d{2})", self.published)
        if not match:
            raise ImportError(f"arXiv 返回了无效发布日期：{self.published!r}")
        return "".join(match.groups())


def normalize_arxiv_id(value: str):
    raw = (value or "").strip().split("?", 1)[0].rstrip("/")
    match = ARXIV_ID_RE.search(raw)
    if not match:
        raise ImportError(f"无法识别 arXiv ID：{value}")
    version = int(match.group("version")) if match.group("version") else None
    return match.group("base"), version


def normalize_arxiv_id_from_text(text: str):
    match = TEXT_ID_RE.search(text or "")
    if not match:
        raise ImportError("文本中没有 arXiv ID")
    return match.group(1), int(match.group(2)) if match.group(2) else None


def _clean(value):
    return " ".join((value or "").split())


def parse_arxiv_atom(xml_text: str):
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise ImportError(f"arXiv 元数据响应无法解析：{exc}") from exc
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entry = root.find("atom:entry", ns)
    if entry is None:
        raise ImportError("arXiv 未返回对应论文")
    base_id, version = normalize_arxiv_id(_clean(entry.findtext("atom:id", namespaces=ns)))
    authors = [_clean(n.findtext("atom:name", namespaces=ns)) for n in entry.findall("atom:author", ns)]
    pdf_url = ""
    for link in entry.findall("atom:link", ns):
        if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
            pdf_url = link.attrib.get("href", "")
            break
    version = version or 1
    return ArxivPaper(
        base_id, version, _clean(entry.findtext("atom:title", namespaces=ns)),
        [a for a in authors if a], _clean(entry.findtext("atom:summary", namespaces=ns)),
        _clean(entry.findtext("atom:published", namespaces=ns)),
        _clean(entry.findtext("atom:updated", namespaces=ns)),
        f"https://arxiv.org/abs/{base_id}v{version}",
        pdf_url or f"https://arxiv.org/pdf/{base_id}v{version}.pdf")


def fetch_arxiv_paper(arxiv_id, session=requests, timeout=30):
    base_id, _ = normalize_arxiv_id(arxiv_id)
    response = session.get(
        ARXIV_API_URL, params={"id_list": base_id},
        headers={"User-Agent": "arxiv-classify-zotero/3.0 (local personal tool)"},
        timeout=timeout)
    response.raise_for_status()
    return parse_arxiv_atom(response.text)


def _creator(name):
    parts = name.strip().split()
    if len(parts) < 2:
        return {"creatorType": "author", "name": name.strip()}
    return {"creatorType": "author", "firstName": " ".join(parts[:-1]), "lastName": parts[-1]}


class ZoteroClient:
    def __init__(self, base_url=ZOTERO_BASE_URL, key_file=None, session=None):
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.key_file = key_file or Path.home() / ".config/arxiv-classify/zotero-local-api-key"
        self.server_id = None
        self.api_key = None
        if self.key_file.exists():
            self.api_key = self.key_file.read_text(encoding="utf-8").strip() or None

    def _url(self, path):
        return self.base_url + "/" + path.lstrip("/")

    def _headers(self, write=False, extra=None):
        headers = {"Zotero-API-Version": "3", "Zotero-Allowed-Request": "1"}
        if write:
            self.connect()
            headers["Zotero-Server-ID"] = self.server_id or ""
            if self.api_key:
                headers["Zotero-API-Key"] = self.api_key
        if extra:
            headers.update(extra)
        return headers

    def connect(self):
        if self.server_id:
            return
        try:
            response = self.session.get(self._url("/"), headers=self._headers(), timeout=5)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ImportError("无法连接 Zotero 本地 API；请确认 Zotero 已启动并开启本地 API") from exc
        self.server_id = response.headers.get("Zotero-Server-ID")
        if not self.server_id:
            raise ImportError("Zotero 未返回 Server ID；需要 Zotero 10 或更高版本")

    def authorize(self):
        self.connect()
        try:
            response = self.session.post(
                self._url("local/authorize"), json={"appName": "ArXiv Classify WebUI"},
                headers={"Zotero-API-Version": "3", "Zotero-Allowed-Request": "1",
                         "Zotero-Server-ID": self.server_id or ""}, timeout=120)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ImportError("Zotero 写入授权失败；请在 Zotero 弹窗中选择“始终允许”") from exc
        payload = response.json()
        self.api_key = payload.get("key")
        if not self.api_key:
            raise ImportError("Zotero 没有返回写入密钥")
        if payload.get("remember"):
            self.key_file.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=".zotero-key-", dir=self.key_file.parent)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(self.api_key + "\n")
                os.replace(temp_name, self.key_file)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)

    def _write(self, method, path, **kwargs):
        if not self.api_key:
            self.authorize()
        extra_headers = kwargs.pop("headers", None)
        timeout = kwargs.pop("timeout", 30)
        for attempt in range(2):
            response = self.session.request(
                method, self._url(path), headers=self._headers(True, extra_headers),
                timeout=timeout, **kwargs)
            if response.status_code != 401:
                try:
                    response.raise_for_status()
                except requests.HTTPError as exc:
                    detail = (response.text or '').strip()[:500]
                    suffix = f"：{detail}" if detail else ''
                    raise ImportError(f"Zotero 请求失败（HTTP {response.status_code}）{suffix}") from exc
                return response
            self.api_key = None
            if self.key_file.exists():
                self.key_file.unlink()
            if attempt == 0:
                self.authorize()
        raise ImportError("Zotero 写入授权已失效")

    def _get_json(self, path, **params):
        response = self.session.get(self._url(path), headers=self._headers(),
                                    params=params or None, timeout=30)
        response.raise_for_status()
        return response.json()

    def collections(self):
        return self._get_json("users/0/collections")

    def ensure_collection(self, name, parent_key=False):
        for row in self.collections():
            data = row.get("data", row)
            if data.get("name") == name and data.get("parentCollection", False) == parent_key:
                return row.get("key") or data["key"]
        payload = self._write("POST", "users/0/collections",
                              json=[{"name": name, "parentCollection": parent_key}],
                              headers={"Zotero-Write-Token": new_write_token()}).json()
        key = (payload.get("success") or {}).get("0")
        if not key:
            raise ImportError(f"创建 Zotero 集合失败：{name}")
        return key

    def ensure_target_collection(self, month):
        temp_key = self.ensure_collection("temp")
        interest_key = self.ensure_collection("arxiv_interest", temp_key)
        return self.ensure_collection(month, interest_key)

    def find_arxiv_item(self, base_id):
        rows = self._get_json("users/0/items/top", q=base_id, qmode="everything")
        for row in rows:
            data = row.get("data", row)
            text = "\n".join(str(data.get(k) or "") for k in
                             ("url", "extra", "archiveLocation", "DOI"))
            try:
                found, _ = normalize_arxiv_id_from_text(text)
            except ImportError:
                continue
            if found.lower() == base_id.lower():
                return row
        return None

    @staticmethod
    def item_arxiv_version(item, paper=None):
        data = item.get("data", item)
        text = "\n".join(str(data.get(k) or "") for k in ("url", "extra", "archiveLocation"))
        match = VERSION_RE.search(text)
        if match:
            return int(match.group(2))
        standalone = re.search(r"arXiv Version:\s*(\d+)", text, re.I)
        if standalone:
            return int(standalone.group(1))
        if paper and data.get("dateAdded") and paper.updated:
            try:
                added = datetime.fromisoformat(data["dateAdded"].replace("Z", "+00:00"))
                revised = datetime.fromisoformat(paper.updated.replace("Z", "+00:00"))
                if added.tzinfo is None:
                    added = added.replace(tzinfo=timezone.utc)
                if revised.tzinfo is None:
                    revised = revised.replace(tzinfo=timezone.utc)
                if added >= revised:
                    return paper.version
            except ValueError:
                pass
        return 1

    @staticmethod
    def _metadata(paper, collection_key, item_type="preprint"):
        metadata = {
            "itemType": item_type, "title": paper.title,
            "creators": [_creator(name) for name in paper.authors],
            "abstractNote": paper.abstract, "date": paper.published[:10], "url": paper.abs_url,
            "archive": "arXiv",
            "archiveLocation": paper.versioned_id, "libraryCatalog": "arXiv.org",
            "extra": (f"arXiv ID: {paper.base_id}\nArXiv Version: {paper.version}\n"
                      f"arXiv: {paper.versioned_id}"),
            "collections": [collection_key]}
        if item_type == "preprint":
            metadata.update({"repository": "arXiv", "archiveID": paper.versioned_id})
        elif item_type == "journalArticle":
            metadata["publicationTitle"] = "arXiv"
        return metadata

    def _create_item(self, data):
        payload = self._write("POST", "users/0/items", json=[data],
                              headers={"Zotero-Write-Token": new_write_token()}).json()
        key = (payload.get("success") or {}).get("0")
        if not key:
            raise ImportError(f"Zotero 创建条目失败：{json.dumps(payload, ensure_ascii=False)}")
        return key

    def _update_parent(self, item, paper, collection_key):
        data = item.get("data", item)
        key = item.get("key") or data.get("key")
        patch = self._metadata(paper, collection_key, data.get("itemType") or "preprint")
        patch.pop("itemType", None)
        patch["collections"] = list(dict.fromkeys((data.get("collections") or []) + [collection_key]))
        self._write("PATCH", f"users/0/items/{key}", json=patch,
                    headers={"If-Unmodified-Since-Version": str(data.get("version", item.get("version", 0)))})
        return key

    def _label_existing_pdfs(self, parent_key, old_version, base_id):
        for row in self._get_json(f"users/0/items/{parent_key}/children"):
            data = row.get("data", row)
            if data.get("itemType") != "attachment" or data.get("contentType") != "application/pdf":
                continue
            title = data.get("title") or "Full Text PDF"
            if re.search(r"\bv\d+\b", title, re.I):
                continue
            key = row.get("key") or data.get("key")
            self._write("PATCH", f"users/0/items/{key}",
                        json={"title": f"{title} (arXiv {base_id}v{old_version})"},
                        headers={"If-Unmodified-Since-Version": str(data.get("version", row.get("version", 0)))})

    def _upload_pdf(self, parent_key, paper, pdf_path):
        attachment_key = self._create_item({
            "itemType": "attachment", "linkMode": "imported_file",
            "title": f"Full Text PDF (arXiv {paper.versioned_id})",
            "contentType": "application/pdf", "filename": pdf_path.name,
            "parentItem": parent_key, "tags": [], "relations": {}})
        content = pdf_path.read_bytes()
        form = {"md5": hashlib.md5(content).hexdigest(), "filename": pdf_path.name,
                "filesize": str(len(content)), "mtime": str(int(pdf_path.stat().st_mtime * 1000))}
        phase1 = self._write(
            "POST", f"users/0/items/{attachment_key}/file", data=form,
            headers={"If-None-Match": "*", "Content-Type": "application/x-www-form-urlencoded"}).json()
        if phase1.get("exists"):
            return attachment_key
        upload_key, upload_url = phase1.get("uploadKey"), phase1.get("url")
        if not upload_key or not upload_url:
            raise ImportError("Zotero 没有返回 PDF 上传地址")
        response = self.session.post(
            urljoin(self.base_url + "/", upload_url),
            data=phase1.get("prefix", "").encode() + content + phase1.get("suffix", "").encode(),
            headers={"Content-Type": phase1.get("contentType", "application/octet-stream")}, timeout=120)
        response.raise_for_status()
        self._write("POST", f"users/0/items/{attachment_key}/file", data={"upload": upload_key},
                    headers={"If-None-Match": "*", "Content-Type": "application/x-www-form-urlencoded"})
        return attachment_key

    def import_paper(self, paper, pdf_path):
        collection_key = self.ensure_target_collection(paper.month)
        existing = self.find_arxiv_item(paper.base_id)
        if existing:
            old_version = self.item_arxiv_version(existing, paper)
            if paper.version <= old_version:
                return {"status": "skipped", "arxiv_id": paper.versioned_id,
                        "item_key": existing.get("key") or existing.get("data", {}).get("key"),
                        "message": f"Zotero 已有 v{old_version}"}
            parent_key = existing.get("key") or existing.get("data", {}).get("key")
            self._label_existing_pdfs(parent_key, old_version, paper.base_id)
            self._update_parent(existing, paper, collection_key)
            self._upload_pdf(parent_key, paper, pdf_path)
            return {"status": "updated", "arxiv_id": paper.versioned_id, "item_key": parent_key}
        parent_key = self._create_item(self._metadata(paper, collection_key))
        self._upload_pdf(parent_key, paper, pdf_path)
        return {"status": "created", "arxiv_id": paper.versioned_id, "item_key": parent_key}


def download_pdf(paper, cache_dir, session=requests, timeout=120):
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{paper.versioned_id.replace('/', '_')}.pdf"
    if path.exists() and path.stat().st_size > 4:
        with path.open("rb") as handle:
            if handle.read(4) == b"%PDF":
                return path
    partial = path.with_suffix(".pdf.part")
    try:
        with session.get(paper.pdf_url, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            with partial.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=131072):
                    if chunk:
                        handle.write(chunk)
        with partial.open("rb") as handle:
            valid = handle.read(4) == b"%PDF"
        if not valid:
            raise ImportError("arXiv 返回的文件不是有效 PDF")
        partial.replace(path)
    finally:
        if partial.exists():
            partial.unlink()
    return path


def import_arxiv_id(arxiv_id, cache_dir: Path, zotero: ZoteroClient,
                    progress: Callable[[str], None] | None = None):
    notify = progress or (lambda _message: None)
    notify("查询 arXiv 最新版本")
    paper = fetch_arxiv_paper(arxiv_id)
    existing = zotero.find_arxiv_item(paper.base_id)
    if existing:
        old_version = zotero.item_arxiv_version(existing, paper)
        if paper.version <= old_version:
            return {"status": "skipped", "arxiv_id": paper.versioned_id,
                    "item_key": existing.get("key") or existing.get("data", {}).get("key"),
                    "message": f"Zotero 已有 v{old_version}"}
    notify(f"下载 {paper.versioned_id} PDF")
    pdf_path = download_pdf(paper, cache_dir)
    notify(f"导入 Zotero / {paper.month}")
    result = zotero.import_paper(paper, pdf_path)
    result.update({"pdf_path": str(pdf_path), "month": paper.month})
    return result
