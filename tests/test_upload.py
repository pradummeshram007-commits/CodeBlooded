"""Upload pipeline: dedup, .txt/.pdf pairing, PDF text extraction, unparseable PDFs, limits."""
from __future__ import annotations

from pathlib import Path

import pytest

from odin.ingest.pdf import extract_pdf_text, text_similarity
from odin.ingest.upload import UploadRejected, doc_id_for, ingest_file
from odin.state.backend import open_file_store

from .conftest import A3_ALL, DOC_IDS, doc_id_of, field, make_llm, reply

pytest.importorskip("pdfplumber")


def _bundle(cfg) -> Path:
    return cfg.paths.bundle_dir / "contracts"


def blank_pdf(pages: int = 1) -> bytes:
    """A valid PDF whose pages carry no text layer at all (like a scan without OCR)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [" + " ".join(f"{3 + i} 0 R" for i in range(pages)) + f"] /Count {pages} >>"]
    objs += ["<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>"] * pages
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def _gov_law_responder(system, messages):
    doc = doc_id_of(messages)
    return reply([field("governing_law", "governing_law", {"law": "x"}, [(f"{doc}:preamble", "NOT IN THE TEXT AT ALL")])]
                 + (A3_ALL if doc == "A3" else []))


def test_upload_dedup_returns_existing_document(any_store, cfg) -> None:
    files = open_file_store(cfg)
    data = (_bundle(cfg) / "A3.txt").read_bytes()
    llm, provider = make_llm(cfg, _gov_law_responder)
    first = ingest_file(data, "A3.txt", store=any_store, files=files, cfg=cfg, llm=llm)
    assert first.outcome == "created" and first.parse_status == "parsed" and first.clauses == 7
    # Alone in the store, A3 amends documents that are not there yet: Thor ran, and says so.
    assert first.thor is not None and first.thor.status == "partial" and "not a bundle document" in first.thor.reason
    assert files.exists(first.storage_path) and first.storage_path == f"A3/{first.sha256}/A3.txt"
    counts, calls = any_store.row_counts(), len(provider.calls)

    again = ingest_file(data, "A3 (copy).txt", store=any_store, files=files, cfg=cfg, llm=llm)
    assert again.outcome == "duplicate" and again.doc_id == "A3" and again.thor is None
    assert any_store.row_counts() == counts                       # no new document, file, clause or extraction
    assert len(provider.calls) == calls                           # no re-extraction


def test_txt_and_pdf_of_one_contract_become_one_document(any_store, cfg) -> None:
    files = open_file_store(cfg)
    txt = ingest_file((_bundle(cfg) / "A1.txt").read_bytes(), "A1.txt", store=any_store, files=files, cfg=cfg,
                      extract=False)
    pdf = ingest_file((_bundle(cfg) / "A1.pdf").read_bytes(), "A1.pdf", store=any_store, files=files, cfg=cfg,
                      extract=False)
    assert (txt.outcome, pdf.outcome) == ("created", "attached")
    assert len(any_store.list_documents()) == 1
    doc = any_store.get_document("A1")
    assert doc.text_source == "txt" and doc.text == (_bundle(cfg) / "A1.txt").read_text(encoding="utf-8")
    assert doc.mime_type == "application/pdf" and doc.original_filename == "A1.pdf"
    assert doc.storage_path == pdf.storage_path and files.download(doc.storage_path)[:5] == b"%PDF-"
    roles = {f.role: f for f in any_store.list_document_files("A1")}
    assert set(roles) == {"text_source", "original"} and roles["original"].similarity > 0.9
    assert len(any_store.list_clauses("A1")) == 16                # segmented from the .txt, not the PDF
    assert not [f for f in any_store.list_flags("A1") if f.type == "contradictory"]


def test_pdf_first_then_txt_takes_over_as_text_source(any_store, cfg) -> None:
    files = open_file_store(cfg)
    pdf = ingest_file((_bundle(cfg) / "C1.pdf").read_bytes(), "C1.pdf", store=any_store, files=files, cfg=cfg,
                      extract=False)
    assert pdf.outcome == "created" and any_store.get_document("C1").text_source == "pdf_extracted"
    txt = ingest_file((_bundle(cfg) / "C1.txt").read_bytes(), "C1.txt", store=any_store, files=files, cfg=cfg,
                      extract=False)
    doc = any_store.get_document("C1")
    assert txt.outcome == "updated" and doc.text_source == "txt" and doc.status == "pending"
    assert doc.original_filename == "C1.pdf"                      # the PDF stays the viewable original
    assert len(any_store.list_clauses("C1")) == 20


def test_mismatched_pdf_is_flagged(store, cfg) -> None:
    files = open_file_store(cfg)
    ingest_file((_bundle(cfg) / "A1.txt").read_bytes(), "A1.txt", store=store, files=files, cfg=cfg, extract=False)
    res = ingest_file((_bundle(cfg) / "D1.pdf").read_bytes(), "A1.pdf", store=store, files=files, cfg=cfg, extract=False)
    assert res.outcome == "attached" and res.similarity < 0.5
    assert [f.type for f in store.list_flags("A1")] == ["contradictory"]


@pytest.mark.parametrize("doc_id", DOC_IDS)
def test_pdf_text_matches_the_txt(cfg, doc_id) -> None:
    pdf = extract_pdf_text((_bundle(cfg) / f"{doc_id}.pdf").read_bytes())
    txt = (_bundle(cfg) / f"{doc_id}.txt").read_text(encoding="utf-8")
    assert pdf.has_text and pdf.pages >= 1
    assert text_similarity(pdf.text, txt) >= 0.9


def test_pdf_without_text_layer_is_unparseable_not_a_crash(store, cfg) -> None:
    llm, provider = make_llm(cfg, _gov_law_responder)
    res = ingest_file(blank_pdf(2), "SCAN1.pdf", store=store, files=open_file_store(cfg), cfg=cfg, llm=llm)
    assert res.outcome == "created" and res.parse_status == "unparseable" and res.clauses == 0
    doc = store.get_document("SCAN1")
    assert doc.status == "failed" and "no text layer" in doc.status_reason and doc.storage_path
    flags = store.list_flags("SCAN1")
    assert [f.type for f in flags] == ["unparseable"] and "2 page(s)" in flags[0].description
    assert res.thor is None and provider.calls == []              # nothing for Thor to read
    assert not store.needs_extraction("SCAN1")


def test_corrupt_pdf_is_unparseable_not_a_crash(store, cfg) -> None:
    res = ingest_file(b"%PDF-1.4 this is not really a pdf", "BROKEN.pdf", store=store, files=open_file_store(cfg),
                      cfg=cfg, extract=False)
    assert res.parse_status == "unparseable"
    assert "could not read the PDF" in store.list_flags("BROKEN")[0].description


def test_rejects_other_types_empty_and_oversized_files(store, cfg) -> None:
    files = open_file_store(cfg)
    with pytest.raises(UploadRejected, match="only .pdf, .txt"):
        ingest_file(b"PK\x03\x04", "contract.docx", store=store, files=files, cfg=cfg)
    with pytest.raises(UploadRejected, match="empty"):
        ingest_file(b"", "X.txt", store=store, files=files, cfg=cfg)
    cfg.upload.max_upload_mb = 0.001
    with pytest.raises(UploadRejected, match="limit"):
        ingest_file(b"x" * 2000, "X.txt", store=store, files=files, cfg=cfg)
    assert store.list_documents() == []


def test_doc_ids_follow_the_filename_stem() -> None:
    assert doc_id_for("A1.pdf") == "A1" and doc_id_for("STD.txt") == "STD"
    assert doc_id_for("My Contract (final).pdf") == "My-Contract-final"
    assert doc_id_for("a:b/c.txt") == "c"
