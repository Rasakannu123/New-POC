"""
Pipeline building blocks used by the LangGraph nodes (pipeline_graph.py).

Flow:
    Input/*.pdf -> convert -> enhance -> assess -> gate -> route -> extract
        -> store in Output/

Concurrency model (one mechanism per bottleneck):
    - Enhance  : ProcessPoolExecutor (CPU-bound OpenCV / NumPy)
    - Assess   : ThreadPoolExecutor  (Tesseract subprocess releases the GIL)
    - Extract  : asyncio.gather      (network-bound API calls)

Per document, a folder is written to Output/<document>/ containing the
split document PDFs and one merged JSON record per document.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter

from src.doc_extraction import config
from src.doc_extraction.cost import cost_block
from src.doc_extraction.layers.conversion import ImageConversionLayer
from src.doc_extraction.layers.extraction import ExtractionEngine, ExtractionResult
from src.doc_extraction.layers.grouping import DocumentGroup, group_pages_by_value
from src.doc_extraction.layers.quality import (
    QualityAssessmentEngine,
    TIER_BLURRY,
    TIER_CLEAR,
    TIER_VERY_BLURRY,
)
from src.doc_extraction.layers.router import ModelRouter, RoutingDecision
from src.doc_extraction.layers.split import (
    VERDICT_UNCLEAR,
    SplitDecision,
    SplitEngine,
)

logger = logging.getLogger("pipeline")


class Pipeline:
    """Pipeline building blocks shared by the LangGraph nodes."""

    def __init__(
        self,
        preprocess_pool: ProcessPoolExecutor,
        assess_pool: ThreadPoolExecutor,
        page_semaphore: int,
    ) -> None:
        self.converter = ImageConversionLayer(dpi=config.DPI)
        self.quality_engine = QualityAssessmentEngine()
        self.router = ModelRouter()
        self.extractor = ExtractionEngine()
        self.split_engine = SplitEngine(no_need_fields=config.NO_NEED_PAGE_FIELDS)
        self.multi_doc_field = (
            config.MULTI_DOC_FIELDS[0] if config.MULTI_DOC_FIELDS else None
        )
        self.preprocess_pool = preprocess_pool
        self.assess_pool = assess_pool
        self.page_semaphore = page_semaphore

    def _encode_pages(self, pages) -> list[bytes]:
        payloads: list[bytes] = []
        for page in pages:
            buffer = io.BytesIO()
            page.convert("RGB").save(buffer, format="PNG")
            payloads.append(buffer.getvalue())
        return payloads

    def _assess(self, pre_binarize_bytes: bytes):
        image = Image.open(io.BytesIO(pre_binarize_bytes))
        return self.quality_engine.assess(image)

    def _classify(self, pre_binarize_bytes: bytes) -> SplitDecision:
        image = Image.open(io.BytesIO(pre_binarize_bytes))
        return self.split_engine.classify(image)

    async def extract_pages(
        self, jobs: list[tuple[int, RoutingDecision, Path]]
    ) -> list[ExtractionResult]:
        """One extraction call per (page, decision, image) job, capped by the semaphore."""
        semaphore = asyncio.Semaphore(self.page_semaphore)
        async_client = ModelRouter.create_async_client()
        extractor = ExtractionEngine(async_client=async_client)

        async def one(decision: RoutingDecision, image_path: Path):
            image = Image.open(image_path)
            async with semaphore:
                return await extractor.extract_async(image, decision)

        try:
            return await asyncio.gather(
                *[one(decision, path) for (_page, decision, path) in jobs]
            )
        finally:
            await async_client.close()

    def _write_skipped_page(
        self,
        source_pdf,
        page_number: int,
        pad: int,
        enhanced_bytes: bytes,
        assessment,
        decision,
    ) -> None:
        document_name = source_pdf.stem
        base_name = f"{document_name}_{page_number:0{pad}d}"
        image_name = f"{base_name}.{config.IMAGE_FORMAT}"
        (config.SKIP_DIR / image_name).write_bytes(enhanced_bytes)

        record = {
            "document": source_pdf.name,
            "page": page_number,
            "image_file": image_name,
            "quality_score": assessment.score,
            "quality_tier": assessment.tier,
            "page_skipped": True,
            "skip_reason": decision.reason or "page matches no_need_page fields",
            "split_reply": decision.raw_reply,
            "extracted_fields": {},
            "field_confidence_scores": {},
            "confidence_score": 0.0,
            "extraction_success": False,
        }
        json_name = f"{base_name}.json"
        (config.SKIP_DIR / json_name).write_text(
            json.dumps(record, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(
            "     %s | skipped by split gate -> %s",
            base_name,
            decision.reason,
        )

    def _write_manual_review_page(
        self,
        source_pdf,
        page_number: int,
        pad: int,
        enhanced_bytes: bytes,
        assessment,
        decision,
        extraction=None,
    ) -> None:
        config.MANUAL_REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        document_name = source_pdf.stem
        base_name = f"{document_name}_{page_number:0{pad}d}"
        image_name = f"{base_name}.{config.IMAGE_FORMAT}"
        (config.MANUAL_REVIEW_DIR / image_name).write_bytes(enhanced_bytes)

        record = {
            "document": source_pdf.name,
            "page": page_number,
            "image_file": image_name,
            "quality_score": assessment.score,
            "quality_tier": assessment.tier,
            "manual_review": True,
            "split_reply": decision.raw_reply,
            "split_reason": decision.reason,
            "extracted_fields": {},
            "field_confidence_scores": {},
            "confidence_score": 0.0,
            "extraction_success": False,
        }
        if extraction is not None:
            confidence_values = list(extraction.confidence_scores.values())
            overall_confidence = (
                round(sum(confidence_values) / len(confidence_values), 1)
                if confidence_values
                else 0.0
            )
            record.update(
                {
                    "model_used": extraction.model,
                    "extracted_fields": extraction.fields,
                    "field_confidence_scores": extraction.confidence_scores,
                    "confidence_score": overall_confidence,
                    "extraction_success": extraction.success,
                    "processing_time_seconds": extraction.processing_time,
                    "cost": cost_block(
                        [
                            {
                                "model": extraction.model,
                                "input_tokens": getattr(
                                    extraction, "input_tokens", 0
                                ),
                                "output_tokens": getattr(
                                    extraction, "output_tokens", 0
                                ),
                            }
                        ]
                    ),
                }
            )
            if extraction.error:
                record["error"] = extraction.error
        json_name = f"{base_name}.json"
        (config.MANUAL_REVIEW_DIR / json_name).write_text(
            json.dumps(record, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(
            "     %s | unclear split reply -> %s",
            base_name,
            config.MANUAL_REVIEW_DIR,
        )


    @staticmethod
    def _write_single_doc_results(
        source_pdf,
        needed_indices: list[int],
        extractions: dict,
    ) -> int:
        page_data = {index + 1: extractions[index] for index in needed_indices}
        if not page_data:
            return 0
        document = DocumentGroup(value=source_pdf.stem, pages=sorted(page_data))
        Pipeline._write_document(
            source_pdf, f"{source_pdf.stem}.pdf", document, page_data
        )
        return 1

    def _write_multi_doc_results(
        self,
        source_pdf,
        pad: int,
        needed_indices: list[int],
        extractions: dict,
    ) -> tuple[int, int]:
        page_data: dict[int, tuple] = {}
        values: dict[int, object] = {}
        for index in needed_indices:
            page_number = index + 1
            enhanced_bytes, assessment, extraction = extractions[index]
            page_data[page_number] = (enhanced_bytes, assessment, extraction)
            raw = extraction.helper_values.get(self.multi_doc_field)
            values[page_number] = raw.strip() if isinstance(raw, str) else raw

        grouping = group_pages_by_value(values)

        for document_index, document in enumerate(grouping.documents, start=1):
            self._write_document(
                source_pdf, f"invoice-{document_index}.pdf", document, page_data
            )

        for page_number in grouping.manual_review:
            enhanced_bytes, assessment, extraction = page_data[page_number]
            decision = SplitDecision(
                verdict=VERDICT_UNCLEAR,
                raw_reply="document grouping",
                reason=(
                    "ambiguous document position - helper value missing "
                    "or conflicting with surrounding pages"
                ),
            )
            self._write_manual_review_page(
                source_pdf,
                page_number,
                pad,
                enhanced_bytes,
                assessment,
                decision,
                extraction=extraction,
            )
        return len(grouping.documents), len(grouping.manual_review)

    @staticmethod
    def _write_document(
        source_pdf,
        pdf_name: str,
        document,
        page_data: dict[int, tuple],
    ) -> None:
        stem = source_pdf.stem
        directory = config.OUTPUT_DIR / stem
        directory.mkdir(parents=True, exist_ok=True)

        reader = PdfReader(source_pdf)
        writer = PdfWriter()
        for page_number in document.pages:
            writer.add_page(reader.pages[page_number - 1])
        with (directory / pdf_name).open("wb") as handle:
            writer.write(handle)

        page_data_flat = {
            page_number: page_data[page_number][2] for page_number in document.pages
        }
        field_order: list[str] = list(config.TEMPLATE_FIELDS)
        for extraction in page_data_flat.values():
            for name in extraction.fields:
                if name not in field_order:
                    field_order.append(name)

        merged_fields: dict = {}
        merged_confidences: dict[str, int] = {}
        for name in field_order:
            for page_number in document.pages:
                extraction = page_data_flat[page_number]
                value = extraction.fields.get(name)
                if isinstance(value, str) and not value.strip():
                    value = None
                if value is not None:
                    merged_fields[name] = value
                    merged_confidences[name] = extraction.confidence_scores.get(
                        name, 0
                    )
                    break
            else:
                merged_fields[name] = None
                merged_confidences[name] = 0

        models_used: list[str] = []
        total_time = 0.0
        extraction_success = False
        errors: list[str] = []
        usages: list[dict] = []
        for page_number in document.pages:
            extraction = page_data_flat[page_number]
            if extraction.model and extraction.model not in models_used:
                models_used.append(extraction.model)
            total_time += extraction.processing_time
            extraction_success = extraction_success or extraction.success
            if extraction.error:
                errors.append(f"page {page_number}: {extraction.error}")
            usages.append(
                {
                    "model": extraction.model,
                    "input_tokens": getattr(extraction, "input_tokens", 0),
                    "output_tokens": getattr(extraction, "output_tokens", 0),
                }
            )

        quality_scores = [
            page_data[page_number][1].score for page_number in document.pages
        ]
        quality_score = round(sum(quality_scores) / len(quality_scores), 1)
        quality_tier = (
            TIER_CLEAR
            if quality_score > 80
            else TIER_BLURRY
            if quality_score >= 50
            else TIER_VERY_BLURRY
        )

        confidence_values = list(merged_confidences.values())
        overall_confidence = (
            round(sum(confidence_values) / len(confidence_values), 1)
            if confidence_values
            else 0.0
        )

        cost = cost_block(usages)
        document_record = {
            "document": source_pdf.name,
            "file": pdf_name,
            "pages": document.pages,
            "page_count": len(document.pages),
            "quality_score": quality_score,
            "quality_tier": quality_tier,
            "extracted_fields": merged_fields,
            "field_confidence_scores": merged_confidences,
            "confidence_score": overall_confidence,
            "extraction_success": extraction_success,
            "models_used": models_used,
            "processing_time_seconds": round(total_time, 2),
            "cost": cost,
        }
        if errors:
            document_record["errors"] = errors
        (directory / f"{pdf_name.removesuffix('.pdf')}.json").write_text(
            json.dumps(document_record, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(
            "     %s/%s | %d page(s) -> %s",
            stem,
            pdf_name,
            len(document.pages),
            document.pages,
        )


def run() -> int:
    """Run the LangGraph pipeline over every PDF in the input folder."""
    from src.doc_extraction.pipeline_graph import run_input_folder

    return run_input_folder()
