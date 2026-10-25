"""Upload pipeline: one file in, one stored + segmented + extracted document out.

    ingest_file(file_bytes, filename) -> UploadResult

1. Accept .pdf / .txt only, within the configured size limit.
2. sha256 the bytes. A file whose sha256 is already stored returns the existing document:
   no duplicate row, no second upload, no re-extraction.
3. Text: a .txt is used as-is; a .pdf goes through pdfplumber. A PDF without a text layer
   (or one that cannot be read) is stored with parse_status=unparseable plus a flag.
4. The document ID is the filename stem (format_spec), so ``A1.txt`` and ``A1.pdf`` are
   ONE document: the .txt is the text source (canonical per format_spec) and the .pdf is
   attached as the viewable original. A PDF whose text does not resemble its .txt is
   flagged.
5. The original goes to the file store at {doc_id}/{sha256}/{filename} BEFORE any row is
   written, and all rows for the file are written in one transaction. A failure therefore
   never leaves a half-ingested document (at worst an unreferenced, content-addressed object).
6. The segmenter runs, then Thor on that document. Thor is idempotent (skips a document
   whose text it already extracted completely) and its LLM cache prevents repeat calls.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Literal

from odin.config import OdinConfig
from odin.ingest.loader import EXTERNAL_ID_RE, classify_kind, clauses_from, text_title
from odin.ingest.pdf import extract_pdf_text, text_similarity
from odin.ingest.segmenter import segment
from odin.state.files import FileStore, object_path
from odin.state.models import Document, DocumentFile, Flag, utcnow
from odin.state.store import StateStore

if TYPE_CHECKING:
    from odin.agents.thor import DocResult
    from odin.llm import LLMClient

MIME_TYPES = {".pdf": "application/pdf", ".txt": "text/plain; charset=utf-8"}
_DOC_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")

Outcome = Literal["created", "updated", "attached", "duplicate"]


class UploadRejected(ValueError):
    """The file was refused before anything was stored (type, size, empty)."""


@dataclass
class UploadResult:
    filename: str
    outcome: Outcome
    doc_id: str
    message: str
    sha256: str
    storage_path: str | None = None
    parse_status: str | None = None
    clauses: int = 0
    similarity: float | None = None
    warnings: list[str] = field(default_factory=list)
    document: Document | None = None
    thor: "DocResult | None" = None
    thor_error: str | None = None

    @property
    def changed(self) -> bool:
        return self.outcome != "duplicate"


def doc_id_for(filename: str) -> str:
    """format_spec: the document ID is the filename stem. Characters unsafe in clause IDs / paths become '-'."""
    stem = Path(filename).stem
    return _DOC_ID_RE.sub("-", stem).strip("-") or "document"


def decode_text(data: bytes) -> tuple[str, str | None]:
    """UTF-8 without newline translation (offsets match the file); BOM dropped; cp1252 as a last resort."""
    try:
        text, warning = data.decode("utf-8"), None
    except UnicodeDecodeError:
        text, warning = data.decode("cp1252", errors="replace"), "file is not valid UTF-8; decoded as Windows-1252"
    return text.removeprefix("﻿"), warning


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _resolve(store: StateStore | None, files: FileStore | None, cfg: OdinConfig | None):
    if store is not None and files is not None and cfg is not None:
        return store, files, cfg
    from odin.runtime import get_runtime

    rt = get_runtime(cfg)
    return store or rt.store, files or rt.files, cfg or rt.cfg


def ingest_file(
    file_bytes: bytes,
    filename: str,
    *,
    store: StateStore | None = None,
    files: FileStore | None = None,
    cfg: OdinConfig | None = None,
    llm: "LLMClient | None" = None,
    extract: bool = True,
    title: str | None = None,
    rel_path: str | None = None,
    source: str = "upload",
    progress: Callable[[str], None] | None = None,
) -> UploadResult:
    """Store, parse, segment and (optionally) extract one uploaded file. See the module docstring."""
    store, files, cfg = _resolve(store, files, cfg)
    say = progress or (lambda _msg: None)
    name = Path(filename).name
    ext = Path(name).suffix.lower()

    # 1. validate ----------------------------------------------------------------------
    if ext not in cfg.upload.allowed_extensions:
        raise UploadRejected(f"{name}: only {', '.join(cfg.upload.allowed_extensions)} files are accepted")
    if not file_bytes:
        raise UploadRejected(f"{name}: the file is empty")
    if len(file_bytes) > cfg.upload.max_upload_bytes:
        raise UploadRejected(f"{name}: {len(file_bytes) / 1e6:.1f} MB is over the {cfg.upload.max_upload_mb:g} MB limit")

    # 2. dedup by content ----------------------------------------------------------------
    sha = _sha256(file_bytes)
    say(f"sha256 {sha[:12]}…")
    known = store.find_file_by_sha(sha)
    if known is not None:
        doc = store.get_document(known.doc_id, include_text=False)
        say(f"already stored as {known.doc_id} ({known.original_filename}); nothing to do")
        return UploadResult(name, "duplicate", known.doc_id, f"identical to {known.original_filename} already stored "
                            f"for {known.doc_id}", sha, known.storage_path, doc.parse_status if doc else None,
                            document=doc)

    doc_id = doc_id_for(name)
    existing = store.get_document(doc_id, include_text=False)
    mime = MIME_TYPES[ext]
    path = object_path(doc_id, sha, name)
    now = utcnow()

    if existing is not None and existing.sha256 == sha:
        # Same text ingested before step 2A (no stored original, no text column): store the file and
        # fill in the text; clauses and extractions stay as they are.
        backfill: dict[str, Any] = {}
        if ext == ".txt" and existing.text_source is None:
            text, _ = decode_text(file_bytes)
            backfill = {"text": text, "text_source": "txt",
                        "parse_status": "parsed" if segment(doc_id, text).method == "numbered" else "fallback"}
        if existing.storage_path is None:
            backfill |= {"storage_path": path, "original_filename": name, "mime_type": mime, "uploaded_at": now}
        files.ensure_bucket()
        files.upload(path, file_bytes, mime)
        with store.transaction():
            store.add_document_file(DocumentFile(doc_id=doc_id, role="text_source" if ext == ".txt" else "original",
                                                 sha256=sha, storage_path=path, original_filename=name, mime_type=mime,
                                                 size_bytes=len(file_bytes), uploaded_at=now))
            if backfill:
                store.upsert_document(existing.model_copy(update=backfill))
        say(f"{doc_id} already had this text; stored the original file")
        return UploadResult(name, "duplicate", doc_id, f"{doc_id} already has this text; original file stored", sha, path,
                            backfill.get("parse_status", existing.parse_status),
                            document=store.get_document(doc_id, include_text=False))

    # 3. text --------------------------------------------------------------------------
    warnings: list[str] = []
    if ext == ".txt":
        text, warning = decode_text(file_bytes)
        if warning:
            warnings.append(warning)
        has_text = bool(text.strip())
        no_text_reason = None if has_text else "the .txt file contains no text"
    else:
        say("extracting PDF text (pdfplumber)")
        pdf = extract_pdf_text(file_bytes)
        text, has_text, no_text_reason = pdf.text, pdf.has_text, pdf.reason
        say(f"{pdf.pages} page(s), {len(text):,} characters" + ("" if has_text else f": {pdf.reason}"))

    existing_source = None
    if existing is not None:
        existing_source = existing.text_source or ("txt" if existing.path.endswith(".txt") else "pdf_extracted")
    plan: Outcome = "created" if existing is None else ("attached" if ext == ".pdf" and existing_source == "txt" else "updated")

    # 4. store the original first --------------------------------------------------------
    files.ensure_bucket()
    say(f"uploading original to {files.describe()}: {path}")
    files.upload(path, file_bytes, mime)

    # 5. rows, all in one transaction ---------------------------------------------------
    result = UploadResult(name, plan, doc_id, "", sha, path, warnings=warnings)
    if plan == "attached":
        assert existing is not None
        full = store.get_document(doc_id)
        sim = text_similarity(text, full.text or "") if has_text and full and full.text else None
        result.similarity, result.parse_status = sim, existing.parse_status
        with store.transaction():
            store.update_document(doc_id, storage_path=path, original_filename=name, mime_type=mime, uploaded_at=now)
            store.add_document_file(DocumentFile(doc_id=doc_id, role="original", sha256=sha, storage_path=path,
                                                 original_filename=name, mime_type=mime, size_bytes=len(file_bytes),
                                                 similarity=sim, uploaded_at=now))
            if not has_text:
                warnings.append(f"PDF text could not be read ({no_text_reason}); attached as the viewable original only")
            elif sim is not None and sim < cfg.upload.min_pair_similarity:
                store.add_flag(Flag(
                    doc_id=doc_id, type="contradictory", raised_by="ingest",
                    description=(f"{name} differs from the text source {existing.original_filename or existing.path} "
                                 f"(text similarity {sim:.2f} < {cfg.upload.min_pair_similarity:.2f}): it may not be the "
                                 f"same contract. The .txt stays the text source."),
                ))
                warnings.append(f"low similarity to the .txt ({sim:.2f}); flagged")
        result.message = (f"attached as the viewable original of {doc_id} (text source stays "
                          f"{existing.original_filename or Path(existing.path).name}"
                          + (f", similarity {sim:.2f})" if sim is not None else ")"))
        say(result.message)
    else:
        seg = segment(doc_id, text) if has_text else None
        parse_status = "unparseable" if seg is None else ("parsed" if seg.method == "numbered" else "fallback")
        preamble = next((c.text for c in seg.clauses if c.kind == "preamble"), text[:2000]) if seg else ""
        banner = text_title(text) if has_text else None
        m = EXTERNAL_ID_RE.search(text[:2000]) if has_text else None
        # The viewable original: a PDF once there is one, else the latest text file.
        keep_pdf_original = ext == ".txt" and existing is not None and existing.mime_type == "application/pdf"
        doc = Document(
            doc_id=doc_id,
            title=title or (existing.title if existing else None) or banner or doc_id,
            text_title=banner,
            path=rel_path or name,
            sha256=sha,
            kind=classify_kind(banner, preamble),  # type: ignore[arg-type]
            external_id=m.group(1) if m else None,
            source=source,
            text=text,
            text_source="txt" if ext == ".txt" else "pdf_extracted",
            parse_status=parse_status,  # type: ignore[arg-type]
            storage_path=None if keep_pdf_original else path,
            original_filename=None if keep_pdf_original else name,
            mime_type=None if keep_pdf_original else mime,
            uploaded_at=now,
        )
        clauses = clauses_from(seg) if seg else []
        with store.transaction():
            store.upsert_document(doc)
            store.replace_clauses(doc_id, clauses)
            store.supersede_flags(doc_id, raised_by="ingest")
            store.add_document_file(DocumentFile(doc_id=doc_id, role="text_source" if ext == ".txt" else "original",
                                                 sha256=sha, storage_path=path, original_filename=name, mime_type=mime,
                                                 size_bytes=len(file_bytes), uploaded_at=now))
            if seg is None:
                store.add_flag(Flag(doc_id=doc_id, type="unparseable", raised_by="ingest",
                                    description=f"{name}: {no_text_reason}"))
                store.set_document_status(doc_id, "failed", f"unparseable: {no_text_reason}", coverage=0.0)
            elif seg.unparseable:
                store.add_flag(Flag(doc_id=doc_id, type="unparseable", raised_by="ingest",
                                    description="; ".join(seg.warnings) or "numbering scheme not recognised; paragraph chunks used"))
        result.parse_status, result.clauses = parse_status, len(clauses)
        if seg is not None:
            warnings += seg.warnings
        verb = "created" if plan == "created" else "updated (new text version)"
        result.message = (f"{doc_id} {verb} from {name}: " + (f"{len(clauses)} clauses ({seg.method})" if seg
                          else f"unparseable, {no_text_reason}"))
        say(result.message)

    # 6. Thor ------------------------------------------------------------------------------
    result.document = store.get_document(doc_id, include_text=False)
    if extract and result.parse_status != "unparseable":
        say("running Thor (idempotent; cached LLM calls are free)")
        result.thor, result.thor_error = run_thor_on(store, cfg, doc_id, llm)
        if result.thor is not None:
            say(f"Thor: {result.thor.status}" + (f" ({result.thor.reason})" if result.thor.reason else ""))
        elif result.thor_error:
            say(result.thor_error)
        result.document = store.get_document(doc_id, include_text=False)
    return result


def run_thor_on(store: StateStore, cfg: OdinConfig, doc_id: str, llm: "LLMClient | None" = None,
                workers: int = 4) -> tuple["DocResult | None", str | None]:
    """Run Thor on one document; problems come back as a message, never as an exception."""
    from odin.agents.thor import Thor
    from odin.llm import LLMClient, llm_config_problem

    if llm is None:
        problem = llm_config_problem(cfg)
        if problem:
            return None, f"Thor not run: {problem}. Fix .env, then run python scripts/run_thor.py --docs {doc_id}"
        llm = LLMClient.from_config(cfg)
    try:
        results = Thor(store, llm, cfg).run([doc_id], workers=workers)
    except Exception as exc:  # noqa: BLE001 - surfaced to the uploader, the document is already stored
        return None, f"Thor failed: {type(exc).__name__}: {str(exc)[:300]}"
    return (results[0] if results else None), None


def ingest_path(path: Path, **kwargs: Any) -> UploadResult:
    """ingest_file for a file on disk (scripts, bundle seeding)."""
    return ingest_file(Path(path).read_bytes(), Path(path).name, **kwargs)
