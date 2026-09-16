"""
Pipeline orchestrator.

Flow:
    Input/*.pdf -> convert -> enhance -> assess -> route -> extract
        -> store in Output/

Concurrency model (one mechanism per bottleneck):
    - Documents  : ThreadPoolExecutor  (Poppler releases the GIL)
    - Preprocess : ProcessPoolExecutor (CPU-bound OpenCV / NumPy)
    - Assess     : ThreadPoolExecutor  (Tesseract subprocess releases the GIL)
    - Extract    : asyncio.gather      (network-bound API calls)

Per page, two files are written to Output/:
    <documentname>_<pageno>_q<qualityscore>.png   enhanced image
    <documentname>_<pageno>_q<qualityscore>.json  extracted data + metadata
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

from PIL import Image

from src.doc_extraction import config
from src.doc_extraction.layers.conversion import ImageConversionLayer
from src.doc_extraction.layers.extraction import ExtractionEngine
from src.doc_extraction.layers.preprocessing import preprocess_page_bytes
from src.doc_extraction.layers.quality import QualityAssessmentEngine
from src.doc_extraction.layers.router import ModelRouter
from src.doc_extraction.layers.split import (
    VERDICT_NO,
    VERDICT_UNCLEAR,
    VERDICT_YES,
    SplitDecision,
    SplitEngine,
)

logger = logging.getLogger("pipeline")

SUPPORTED_EXTENSIONS = {".pdf"}


class Pipeline:
    """Runs the full conversion -> extraction pipeline with staged concurrency."""

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
        self.preprocess_pool = preprocess_pool
        self.assess_pool = assess_pool
        self.page_semaphore = page_semaphore

    def process_pdf(self, pdf_path) -> tuple[int, int]:
        """Process one PDF; returns (pages_done, pages_failed)."""
        logger.info("Processing: %s", pdf_path.name)
        started = time.perf_counter()

        result = self.converter.convert_pages(pdf_path)
        if not result.success:
            logger.error("  -> FAILED: %s", result.error)
            return 0, 0

        if result.page_count == 0:
            return 0, 0

        page_bytes = self._encode_pages(result.pages)

        enhanced_futures = [
            self.preprocess_pool.submit(preprocess_page_bytes, payload)
            for payload in page_bytes
        ]
        preprocessed = [future.result() for future in enhanced_futures]

        assess_futures = [
            self.assess_pool.submit(self._assess, pre_binarize_bytes)
            for (_enhanced, pre_binarize_bytes, _angle, _steps) in preprocessed
        ]
        if self.split_engine.enabled:
            split_futures = [
                self.assess_pool.submit(self._classify, pre_binarize_bytes)
                for (_enhanced, pre_binarize_bytes, _angle, _steps) in preprocessed
            ]
        else:
            split_futures = []

        assessments = [future.result() for future in assess_futures]
        if split_futures:
            split_decisions = [future.result() for future in split_futures]
        else:
            split_decisions = [
                SplitDecision(verdict=VERDICT_NO, reason="no_need_page gate disabled")
                for _ in preprocessed
            ]

        needed_indices = [
            index
            for index, decision in enumerate(split_decisions)
            if decision.verdict == VERDICT_NO
        ]

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            extracted = loop.run_until_complete(
                self._extract_all(preprocessed, assessments, needed_indices)
            )
        else:
            extracted = asyncio.run(
                self._extract_all(preprocessed, assessments, needed_indices)
            )

        extractions = dict(zip(needed_indices, extracted))

        pad = max(1, len(str(result.page_count)))
        for page_number, split_decision in enumerate(split_decisions, start=1):
            index = page_number - 1
            enhanced_bytes = preprocessed[index][0]
            assessment = assessments[index]
            if split_decision.verdict == VERDICT_YES:
                self._write_skipped_page(
                    result.source_pdf,
                    page_number,
                    pad,
                    enhanced_bytes,
                    assessment,
                    split_decision,
                )
            elif split_decision.verdict == VERDICT_UNCLEAR:
                self._write_manual_review_page(
                    result.source_pdf,
                    page_number,
                    pad,
                    enhanced_bytes,
                    assessment,
                    split_decision,
                )
            else:
                enhanced_bytes, assessment, extraction = extractions[index]
                self._write_page(
                    result.source_pdf, page_number, pad, enhanced_bytes, assessment, extraction
                )

        skipped_count = sum(1 for d in split_decisions if d.verdict == VERDICT_YES)
        review_count = sum(1 for d in split_decisions if d.verdict == VERDICT_UNCLEAR)
        logger.info(
            "  -> OK: %d page(s) in %.2fs (%d extracted, %d skipped, %d manual-review)",
            result.page_count,
            time.perf_counter() - started,
            len(needed_indices),
            skipped_count,
            review_count,
        )
        return result.page_count, 0

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

    async def _extract_all(self, preprocessed, assessments, indices):
        semaphore = asyncio.Semaphore(self.page_semaphore)
        async_client = ModelRouter.create_async_client()
        extractor = ExtractionEngine(async_client=async_client)

        async def one(enhanced_bytes, assessment):
            decision = self.router.route(assessment)
            image = Image.open(io.BytesIO(enhanced_bytes))
            async with semaphore:
                extraction = await extractor.extract_async(image, decision)
            return enhanced_bytes, assessment, extraction

        tasks = [
            one(preprocessed[index][0], assessments[index])
            for index in indices
        ]
        try:
            return await asyncio.gather(*tasks)
        finally:
            await async_client.close()

    def _write_page(
        self,
        source_pdf,
        page_number: int,
        pad: int,
        enhanced_bytes: bytes,
        assessment,
        extraction,
    ) -> None:
        document_name = source_pdf.stem
        base_name = f"{document_name}_{page_number:0{pad}d}"
        image_name = f"{base_name}.{config.IMAGE_FORMAT}"
        (config.OUTPUT_DIR / image_name).write_bytes(enhanced_bytes)

        confidence_values = list(extraction.confidence_scores.values())
        overall_confidence = (
            round(sum(confidence_values) / len(confidence_values), 1)
            if confidence_values
            else 0.0
        )

        record = {
            "document": source_pdf.name,
            "page": page_number,
            "image_file": image_name,
            "quality_score": assessment.score,
            "quality_tier": assessment.tier,
            "model_used": extraction.model,
            "extracted_fields": extraction.fields,
            "field_confidence_scores": extraction.confidence_scores,
            "confidence_score": overall_confidence,
            "extraction_success": extraction.success,
            "processing_time_seconds": extraction.processing_time,
        }
        if extraction.error:
            record["error"] = extraction.error

        json_name = f"{base_name}.json"
        (config.OUTPUT_DIR / json_name).write_text(
            json.dumps(record, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        logger.info(
            "     %s | score=%.1f tier=%s | model=%s | %d field(s) in %.1fs -> %s",
            image_name,
            assessment.score,
            assessment.tier,
            extraction.model,
            len(extraction.fields),
            extraction.processing_time,
            json_name,
        )

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


def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )

    config.INPUT_DIR.mkdir(parents=True, exist_ok=True)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(
        p for p in config.INPUT_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    if not pdf_files:
        logger.info(
            "No PDF documents found in '%s'. "
            "Drop PDF files into the input folder and run again.",
            config.INPUT_DIR,
        )
        return 0

    logger.info("Found %d PDF document(s) in the input folder.", len(pdf_files))

    succeeded = 0
    failed = 0
    total_images = 0

    with ProcessPoolExecutor(max_workers=config.PREPROCESS_WORKERS) as preprocess_pool, \
            ThreadPoolExecutor(max_workers=config.ASSESS_WORKERS) as assess_pool:
        pipeline = Pipeline(preprocess_pool, assess_pool, config.MAX_CONCURRENT_PAGES)

        with ThreadPoolExecutor(max_workers=config.MAX_CONCURRENT_DOCUMENTS) as doc_pool:
            futures = {doc_pool.submit(pipeline.process_pdf, pdf): pdf for pdf in pdf_files}
            for future, pdf in futures.items():
                try:
                    pages_done, _ = future.result()
                    if pages_done:
                        succeeded += 1
                        total_images += pages_done
                    else:
                        failed += 1
                except Exception as exc:
                    failed += 1
                    logger.error("  -> FAILED: %s: %s", pdf.name, exc)

    logger.info(
        "Done. %d document(s) succeeded, %d failed, %d image(s) written to '%s'.",
        succeeded,
        failed,
        total_images,
        config.OUTPUT_DIR,
    )
    return 1 if failed else 0