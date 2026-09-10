"""
Pipeline orchestrator.

Flow:
    Input/*.pdf -> convert -> enhance -> assess -> route -> extract
        -> store in Output/

Per page, two files are written to Output/:
    <documentname>_<pageno>_q<qualityscore>.png   enhanced image
    <documentname>_<pageno>_q<qualityscore>.json  extracted data + metadata
"""

from __future__ import annotations

import json
import logging
import time

from src.doc_extraction import config
from src.doc_extraction.layers.conversion import ImageConversionLayer
from src.doc_extraction.layers.extraction import ExtractionEngine
from src.doc_extraction.layers.preprocessing import ImagePreprocessingEngine
from src.doc_extraction.layers.quality import QualityAssessmentEngine
from src.doc_extraction.layers.router import ModelRouter

SUPPORTED_EXTENSIONS = {".pdf"}


def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("pipeline")

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

    converter = ImageConversionLayer(dpi=config.DPI)
    preprocessor = ImagePreprocessingEngine()
    quality_engine = QualityAssessmentEngine()
    router = ModelRouter()
    extractor = ExtractionEngine()

    succeeded = 0
    failed = 0
    total_images = 0

    for pdf_path in pdf_files:
        logger.info("Processing: %s", pdf_path.name)
        started = time.perf_counter()

        result = converter.convert_pages(pdf_path)
        if not result.success:
            failed += 1
            logger.error("  -> FAILED: %s", result.error)
            continue

        pad = max(1, len(str(result.page_count)))
        document_name = pdf_path.stem

        for page_number, page_image in enumerate(result.pages, start=1):
            enhanced, prep_report = preprocessor.enhance_with_report(page_image)

            assessment = quality_engine.assess(
                prep_report.pre_binarize_image or enhanced
            )

            decision = router.route(assessment)

            extraction = extractor.extract(enhanced, decision)

            base_name = (
                f"{document_name}_{page_number:0{pad}d}"
                f"_q{int(round(assessment.score))}"
            )
            image_name = f"{base_name}.{config.IMAGE_FORMAT}"
            enhanced.save(str(config.OUTPUT_DIR / image_name))
            total_images += 1

            confidence_values = list(extraction.confidence_scores.values())
            overall_confidence = (
                round(sum(confidence_values) / len(confidence_values), 1)
                if confidence_values
                else 0.0
            )

            record = {
                "document": pdf_path.name,
                "page": page_number,
                "image_file": image_name,
                "quality_score": assessment.score,
                "quality_tier": assessment.tier,
                "model_used": decision.model,
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
                "     %s | score=%.1f tier=%s | model=%s | %d field(s) "
                "in %.1fs -> %s",
                image_name,
                assessment.score,
                assessment.tier,
                decision.model,
                len(extraction.fields),
                extraction.processing_time,
                json_name,
            )

        succeeded += 1
        logger.info(
            "  -> OK: %d page(s) processed in %.2fs",
            result.page_count,
            time.perf_counter() - started,
        )

    logger.info(
        "Done. %d document(s) succeeded, %d failed, %d image(s) written to '%s'.",
        succeeded,
        failed,
        total_images,
        config.OUTPUT_DIR,
    )
    return 1 if failed else 0