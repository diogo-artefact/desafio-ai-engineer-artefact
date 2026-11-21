from __future__ import annotations

import csv
import io
import json
import logging
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pdfplumber
from google.genai import errors as genai_errors
from sqlalchemy import delete

from emporio.db.schema import (
    AuditLogRow,
    CategoryRow,
    CustomerRow,
    KnowledgeSourceRow,
    OrderItemRow,
    OrderRow,
    PolicyChunkRow,
    ProductRow,
    PromotionRow,
    session_scope,
)
from emporio.etl.embeddings import Embedder

logger = logging.getLogger(__name__)

REQUIRED_CSV_TABLES: tuple[str, ...] = (
    "categories",
    "products",
    "promotions",
    "customers",
    "orders",
    "order_items",
)

KNOWN_BRANDS: tuple[str, ...] = (
    "casio",
    "condor",
    "cort",
    "crafter",
    "epiphone",
    "fender",
    "giannini",
    "gibson",
    "ibanez",
    "kala",
    "kalani",
    "korg",
    "martin",
    "michael",
    "music man",
    "nord",
    "ohana",
    "pearl",
    "prs",
    "roland",
    "rozini",
    "shelby",
    "shelter",
    "squier",
    "strinberg",
    "tagima",
    "takamine",
    "tama",
    "taylor",
    "yamaha",
)

SPEC_LABELS_PT: dict[str, str] = {
    "top": "tampo",
    "back_sides": "fundo/laterais",
    "body": "corpo",
    "neck": "braço",
    "strings": "cordas",
    "scale": "escala",
    "electronics": "captação elétrica",
    "color": "cor",
    "shells": "cascos",
    "pieces": "peças",
    "hardware": "ferragens",
    "keys": "teclas",
    "type": "tipo",
    "polyphony": "polifonia",
}

PDF_HEADER_LINE = "Empório da Música Manual de Políticas e Procedimentos"
SECTION_HEADING_RE = re.compile(r"^(\d+)\.\s+([A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇ].+)$")
SUBSECTION_HEADING_RE = re.compile(r"^(\d+\.\d+)\s+([A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇ].+)$")
PAGE_FOOTER_RE = re.compile(r"^Página\s+\d+$")


@dataclass(frozen=True)
class AuditEntry:
    entity_type: str
    entity_id: str
    issue_type: str
    detail: str
    raw_value: str = ""
    curated_value: str = ""


@dataclass(frozen=True)
class CsvIngestReport:
    categories: int
    products: int
    sellable_products: int
    promotions: int
    active_promotions: int
    customers: int
    orders: int
    order_items: int
    audit_entries: int


@dataclass(frozen=True)
class PdfIngestReport:
    filename: str
    policy_chunks: int
    embedded_chunks: int
    audit_entries: int


@dataclass(frozen=True)
class ETLReport:
    csv: CsvIngestReport
    pdf: PdfIngestReport


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_accents.lower()).strip()


def normalize_phone_digits(phone: str) -> str:
    return re.sub(r"\D", "", phone)


def _find_brands(text: str) -> set[str]:
    norm = normalize_text(text)
    found: set[str] = set()
    for brand in KNOWN_BRANDS:
        if re.search(rf"\b{re.escape(brand)}\b", norm):
            found.add(brand)
    return found


def _has_spec_conflict(description: str, specs: dict[str, Any]) -> str | None:
    norm_desc = normalize_text(description)
    if "keys" in specs:
        match = re.search(r"\b(\d{2,3})\s+teclas\b", norm_desc)
        if match and match.group(1) != str(specs["keys"]).strip():
            return f"teclas na descrição ({match.group(1)}) != specs ({specs['keys']})"
    if "strings" in specs and str(specs["strings"]).isdigit():
        match = re.search(r"\b(\d)\s+cordas\b", norm_desc)
        if match and match.group(1) != str(specs["strings"]).strip():
            return f"cordas na descrição ({match.group(1)}) != specs ({specs['strings']})"
    return None


def _build_factual_description(name: str, category_name: str, specs: dict[str, Any]) -> str:
    parts = [f"{SPEC_LABELS_PT.get(k, k)}: {v}" for k, v in specs.items()]
    if parts:
        return f"{name} ({category_name}). Especificações registradas: {', '.join(parts)}."
    return f"{name} ({category_name})."


def _sanitize_product_description(
    product_id: str,
    name: str,
    category_name: str,
    raw_description: str,
    specs: dict[str, Any],
) -> tuple[str, AuditEntry | None]:
    name_brands = _find_brands(name)
    desc_brands = _find_brands(raw_description)
    conflicting_brands = sorted(desc_brands - name_brands) if name_brands else []
    spec_conflict = _has_spec_conflict(raw_description, specs)

    if not conflicting_brands and not spec_conflict:
        return raw_description, None

    reasons: list[str] = []
    if conflicting_brands:
        reasons.append(
            f"marca no nome ({', '.join(sorted(name_brands))}) diverge da descrição "
            f"({', '.join(conflicting_brands)})"
        )
    if spec_conflict:
        reasons.append(spec_conflict)

    curated = _build_factual_description(name, category_name, specs)
    audit = AuditEntry(
        entity_type="product",
        entity_id=product_id,
        issue_type="description_mismatch",
        detail="; ".join(reasons),
        raw_value=raw_description,
        curated_value=curated,
    )
    return curated, audit


def _identify_csv_table(filename: str) -> str | None:
    stem = Path(filename).stem.lower()
    for table in sorted(REQUIRED_CSV_TABLES, key=len, reverse=True):
        if stem == table or stem.endswith(f"- {table}") or stem.endswith(f"_{table}"):
            return table
    return None


def _parse_csv_bytes(payload: bytes) -> list[dict[str, str]]:
    text = payload.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def parse_policy_pdf_bytes(pdf_bytes: bytes) -> tuple[list[dict[str, Any]], list[AuditEntry]]:
    chunks: list[dict[str, Any]] = []
    audits: list[AuditEntry] = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        if pdf.pages:
            cover_text = (pdf.pages[0].extract_text() or "").strip()
            if cover_text:
                chunks.append(
                    {
                        "chunk_id": "sec-0",
                        "section_number": "0",
                        "parent_title": "Capa e Dados de Contato",
                        "title": "Capa e Dados de Contato",
                        "content": cover_text,
                        "page_start": 1,
                        "page_end": 1,
                    }
                )

        current_section_num = ""
        current_parent_title = ""
        current: dict[str, Any] | None = None
        expected_section = 1

        def flush_current() -> None:
            nonlocal current
            if current is None:
                return
            content = "\n".join(current.pop("lines")).strip()
            if content:
                current["content"] = content
                chunks.append(current)
            current = None

        for page_idx in range(1, len(pdf.pages)):
            page_num = page_idx + 1
            raw_text = pdf.pages[page_idx].extract_text() or ""
            for raw_line in raw_text.splitlines():
                line = raw_line.strip()
                if not line or line == PDF_HEADER_LINE or PAGE_FOOTER_RE.match(line):
                    continue

                top_match = SECTION_HEADING_RE.match(line)
                if (
                    top_match
                    and int(top_match.group(1)) == expected_section
                    and ":" not in top_match.group(2)
                ):
                    flush_current()
                    current_section_num = top_match.group(1)
                    current_parent_title = top_match.group(2).strip()
                    current = {
                        "chunk_id": f"sec-{current_section_num}",
                        "section_number": current_section_num,
                        "parent_title": current_parent_title,
                        "title": current_parent_title,
                        "lines": [],
                        "page_start": page_num,
                        "page_end": page_num,
                    }
                    expected_section += 1
                    continue

                sub_match = SUBSECTION_HEADING_RE.match(line)
                if (
                    sub_match
                    and current_section_num
                    and sub_match.group(1).startswith(f"{current_section_num}.")
                ):
                    flush_current()
                    sub_num, sub_title = sub_match.group(1), sub_match.group(2).strip()
                    current = {
                        "chunk_id": f"sec-{sub_num}",
                        "section_number": sub_num,
                        "parent_title": current_parent_title,
                        "title": sub_title,
                        "lines": [],
                        "page_start": page_num,
                        "page_end": page_num,
                    }
                    continue

                if current is not None:
                    current["lines"].append(line)
                    current["page_end"] = page_num

        flush_current()

        if not chunks and pdf.pages:
            for page_idx, page in enumerate(pdf.pages, start=1):
                txt = (page.extract_text() or "").strip()
                if txt:
                    chunks.append(
                        {
                            "chunk_id": f"page-{page_idx}",
                            "section_number": str(page_idx),
                            "parent_title": f"Página {page_idx}",
                            "title": f"Página {page_idx}",
                            "content": txt,
                            "page_start": page_idx,
                            "page_end": page_idx,
                        }
                    )

    full_text = "\n".join(c["content"] for c in chunks)
    phones = sorted(set(re.findall(r"\(\d{2}\)\s*\d{4,5}-\d{4}", full_text)))
    if len(phones) > 1:
        audits.append(
            AuditEntry(
                entity_type="policy_pdf",
                entity_id="contacts",
                issue_type="conflicting_phone_numbers",
                detail=(
                    "Manual lista dois telefones/WhatsApp diferentes entre capa/seção 1 e seção 7."
                ),
                raw_value=", ".join(phones),
                curated_value=(
                    "Priorizar (67) 3341-4444 (capa e ficha cadastral) "
                    "e informar (67) 3321-4500 (seção 7)."
                ),
            )
        )
    if "empóriodamusica.com.br" in full_text.lower():
        audits.append(
            AuditEntry(
                entity_type="policy_pdf",
                entity_id="email",
                issue_type="accented_email_typo",
                detail="Seção 1.2 grafa e-mail com acento (domínio inválido), diferente da capa.",
                raw_value="contato@empóriodamusica.com.br",
                curated_value="contato@emporiodamusica.com.br",
            )
        )

    return chunks, audits


def _contextual_chunk_text(chunk: dict[str, Any]) -> str:
    if chunk["parent_title"] == chunk["title"]:
        header = f"{chunk['section_number']}. {chunk['title']}"
    else:
        header = f"{chunk['parent_title']} > {chunk['section_number']} {chunk['title']}"
    return f"{header}\n{chunk['content']}"


def _to_audit_rows(audits: list[AuditEntry]) -> list[AuditLogRow]:
    return [
        AuditLogRow(
            entity_type=a.entity_type,
            entity_id=a.entity_id,
            issue_type=a.issue_type,
            detail=a.detail,
            raw_value=a.raw_value,
            curated_value=a.curated_value,
        )
        for a in audits
    ]


def ingest_store_csvs(files: Mapping[str, bytes], db_path: Path | str) -> CsvIngestReport:
    resolved: dict[str, tuple[str, list[dict[str, str]]]] = {}
    for filename, payload in files.items():
        table = _identify_csv_table(filename)
        if table is not None:
            resolved[table] = (filename, _parse_csv_bytes(payload))

    missing = [table for table in REQUIRED_CSV_TABLES if table not in resolved]
    if missing:
        raise ValueError("Arquivos CSV obrigatórios ausentes: " + ", ".join(missing))

    raw_categories = resolved["categories"][1]
    raw_products = resolved["products"][1]
    raw_promotions = resolved["promotions"][1]
    raw_customers = resolved["customers"][1]
    raw_orders = resolved["orders"][1]
    raw_order_items = resolved["order_items"][1]

    cat_names = {int(row["category_id"]): row["name"].strip() for row in raw_categories}
    ordered_product_ids = {int(row["product_id"]) for row in raw_order_items}
    audits: list[AuditEntry] = []

    email_counts = Counter(normalize_text(c["email"]) for c in raw_customers)
    for email_norm, count in sorted(email_counts.items()):
        if count > 1:
            ids = [
                c["customer_id"]
                for c in raw_customers
                if normalize_text(c["email"]) == email_norm
            ]
            audits.append(
                AuditEntry(
                    entity_type="customer",
                    entity_id=",".join(ids),
                    issue_type="duplicate_customer_email",
                    detail=f"E-mail compartilhado por {count} cadastros distintos de clientes.",
                    raw_value=email_norm,
                    curated_value=(
                        "Cadastros preservados; verificação de pedido exige "
                        "order_id + e-mail/telefone."
                    ),
                )
            )

    product_rows: list[ProductRow] = []
    sellable_count = 0
    for row in raw_products:
        product_id = int(row["product_id"])
        category_id = int(row["category_id"])
        category_name = cat_names[category_id]
        name = row["name"].strip()
        price_brl = float(row["price_brl"])
        raw_desc = row["description"].strip()
        raw_stock = int(row["stock_quantity"])
        status = row["status"].strip().lower()
        specs: dict[str, Any] = json.loads(row["specs"]) if row["specs"].strip() else {}

        stock = raw_stock
        if status == "discontinued" and raw_stock > 0:
            stock = 0
            audits.append(
                AuditEntry(
                    entity_type="product",
                    entity_id=str(product_id),
                    issue_type="discontinued_nonzero_stock",
                    detail=f"Produto descontinuado ({name}) tinha estoque {raw_stock} no CSV.",
                    raw_value=str(raw_stock),
                    curated_value="0",
                )
            )

        if status == "coming_soon" and product_id in ordered_product_ids:
            audits.append(
                AuditEntry(
                    entity_type="product",
                    entity_id=str(product_id),
                    issue_type="coming_soon_in_orders",
                    detail=(
                        f"Produto em pré-lançamento ({name}) aparece em pedidos históricos; "
                        "registro mantido com is_sellable=False."
                    ),
                    raw_value=f"status={status}, stock={raw_stock}",
                    curated_value="is_sellable=False",
                )
            )

        curated_desc, mismatch_audit = _sanitize_product_description(
            product_id=str(product_id),
            name=name,
            category_name=category_name,
            raw_description=raw_desc,
            specs=specs,
        )
        if mismatch_audit is not None:
            audits.append(mismatch_audit)

        is_sellable = status == "active" and stock > 0
        if is_sellable:
            sellable_count += 1

        specs_text = " ".join(f"{k} {v}" for k, v in specs.items())
        search_text = normalize_text(f"{name} {category_name} {curated_desc} {specs_text}")

        product_rows.append(
            ProductRow(
                product_id=product_id,
                category_id=category_id,
                name=name,
                price_brl=price_brl,
                description=curated_desc,
                raw_description=raw_desc,
                stock_quantity=stock,
                status=status,
                is_sellable=is_sellable,
                specs_json=json.dumps(specs, ensure_ascii=False),
                created_at=row["created_at"].strip(),
                search_text=search_text,
            )
        )

    promotion_rows: list[PromotionRow] = []
    active_promos = 0
    for row in raw_promotions:
        is_active = str(row["is_active"]).strip() in ("1", "true", "True")
        if is_active:
            active_promos += 1
        promotion_rows.append(
            PromotionRow(
                promotion_id=int(row["promotion_id"]),
                product_id=int(row["product_id"]),
                discount_percent=float(row["discount_percent"]),
                description=row["description"].strip(),
                is_active=is_active,
            )
        )

    uploaded_names = [resolved[t][0] for t in REQUIRED_CSV_TABLES]

    with session_scope(db_path) as session:
        session.execute(delete(AuditLogRow).where(AuditLogRow.entity_type != "policy_pdf"))
        session.execute(delete(OrderItemRow))
        session.execute(delete(OrderRow))
        session.execute(delete(PromotionRow))
        session.execute(delete(ProductRow))
        session.execute(delete(CustomerRow))
        session.execute(delete(CategoryRow))

        session.add_all(
            [
                CategoryRow(
                    category_id=int(c["category_id"]),
                    name=c["name"].strip(),
                    description=c["description"].strip(),
                )
                for c in raw_categories
            ]
        )
        session.add_all(
            [
                CustomerRow(
                    customer_id=int(c["customer_id"]),
                    name=c["name"].strip(),
                    name_normalized=normalize_text(c["name"]),
                    phone=c["phone"].strip(),
                    phone_digits=normalize_phone_digits(c["phone"]),
                    email=c["email"].strip(),
                    email_normalized=normalize_text(c["email"]),
                    city=c["city"].strip(),
                )
                for c in raw_customers
            ]
        )
        session.flush()
        session.add_all(product_rows)
        session.add_all(
            [
                OrderRow(
                    order_id=int(o["order_id"]),
                    customer_id=int(o["customer_id"]),
                    order_date=o["order_date"].strip(),
                    status=o["status"].strip().lower(),
                    total_brl=float(o["total_brl"]),
                    payment_method=o["payment_method"].strip().lower(),
                    tracking_code=o["tracking_code"].strip(),
                    estimated_delivery=o["estimated_delivery"].strip(),
                    notes=o["notes"].strip(),
                )
                for o in raw_orders
            ]
        )
        session.flush()
        session.add_all(promotion_rows)
        session.add_all(
            [
                OrderItemRow(
                    order_id=int(it["order_id"]),
                    product_id=int(it["product_id"]),
                    quantity=int(it["quantity"]),
                )
                for it in raw_order_items
            ]
        )
        session.add_all(_to_audit_rows(audits))
        session.flush()
        session.merge(
            KnowledgeSourceRow(
                source_key="store_csvs",
                file_names_json=json.dumps(uploaded_names, ensure_ascii=False),
                record_count=len(raw_products),
                audit_count=len(audits),
                uploaded_at=datetime.now(UTC).isoformat(),
            )
        )

    return CsvIngestReport(
        categories=len(raw_categories),
        products=len(raw_products),
        sellable_products=sellable_count,
        promotions=len(raw_promotions),
        active_promotions=active_promos,
        customers=len(raw_customers),
        orders=len(raw_orders),
        order_items=len(raw_order_items),
        audit_entries=len(audits),
    )


def ingest_policy_pdf(
    pdf_bytes: bytes,
    db_path: Path | str,
    filename: str = "políticas_da_loja.pdf",
    embedder: Embedder | None = None,
) -> PdfIngestReport:
    chunks, audits = parse_policy_pdf_bytes(pdf_bytes)
    if not chunks:
        raise ValueError("Não foi possível extrair texto legível do PDF enviado.")

    vectors: list[list[float] | None] = [None] * len(chunks)
    if embedder is not None:
        try:
            texts = [_contextual_chunk_text(chunk) for chunk in chunks]
            computed = embedder.embed_documents(texts)
            if len(computed) == len(chunks):
                vectors = computed
        except (genai_errors.APIError, httpx.HTTPError, OSError) as exc:
            logger.warning("Falha ao gerar embeddings do PDF: %s", exc)

    embedded_count = sum(1 for v in vectors if v is not None)

    with session_scope(db_path) as session:
        session.execute(delete(AuditLogRow).where(AuditLogRow.entity_type == "policy_pdf"))
        session.execute(delete(PolicyChunkRow))

        session.add_all(
            [
                PolicyChunkRow(
                    chunk_id=chunk["chunk_id"],
                    section_number=chunk["section_number"],
                    parent_title=chunk["parent_title"],
                    title=chunk["title"],
                    content=chunk["content"],
                    page_start=chunk["page_start"],
                    page_end=chunk["page_end"],
                    embedding_json=json.dumps(vec) if vec is not None else None,
                )
                for chunk, vec in zip(chunks, vectors, strict=True)
            ]
        )
        session.add_all(_to_audit_rows(audits))
        session.merge(
            KnowledgeSourceRow(
                source_key="policy_pdf",
                file_names_json=json.dumps([filename], ensure_ascii=False),
                record_count=len(chunks),
                audit_count=len(audits),
                uploaded_at=datetime.now(UTC).isoformat(),
            )
        )

    return PdfIngestReport(
        filename=filename,
        policy_chunks=len(chunks),
        embedded_chunks=embedded_count,
        audit_entries=len(audits),
    )


def load_raw_dir(
    raw_dir: Path | str,
    db_path: Path | str,
    embedder: Embedder | None = None,
) -> ETLReport:
    source = Path(raw_dir)
    csv_files = {p.name: p.read_bytes() for p in sorted(source.glob("*.csv"))}
    pdf_path = source / "políticas_da_loja.pdf"
    csv_report = ingest_store_csvs(csv_files, db_path=db_path)
    pdf_report = ingest_policy_pdf(
        pdf_path.read_bytes(),
        db_path=db_path,
        filename=pdf_path.name,
        embedder=embedder,
    )
    return ETLReport(csv=csv_report, pdf=pdf_report)
