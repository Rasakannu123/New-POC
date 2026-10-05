# Document Extraction — How It Works

## What it does

The system converts **PDF documents into structured JSON data** automatically.
For example, it reads a scanned invoice and pulls out the document number,
date, buyer, seller and totals — with a confidence score for every field.

---

## The pipeline and LangGraph

The whole process is built with **LangGraph**, a library for building AI
workflows as **graphs of steps**. Two concepts matter:

- **Nodes** — the steps of the workflow. Here: one node per feature (6 total).
- **State** — a shared data object that flows through the graph. Each node
  reads what it needs, adds its results, and passes state to the next node.

The graph for one document looks like this:

```
START → convert → enhance → assess → route → extract → output → END
```

The order is fixed and explicit — every document follows the same path.

**Why LangGraph?**

- The run order is declared once, in one place — easy to see and change.
- Each feature is an independent node — easy to test, replace or extend.
- The shared state keeps every step aligned to the same pages.
- Errors are stored in the state and reported at the end, so one broken
  document never crashes a batch run.
- Both entry points — the command line (`main.py`) and the web UI (`app.py`) —
  run **the exact same graph**.

**One run per PDF:** each document flows through the graph independently.
Along the way, every node prints what it is doing, so the terminal shows live
progress.

---

## The 6 features

### 1. Convert — PDF to page images
**What:** turns the PDF into one image per page.
**Why:** all later steps work on images, not on PDF files.

### 2. Enhance — image cleanup
**What:** cleans each page image — sharper, straighter, better contrast.
**Why:** real documents are scans and photos — often tilted, blurry or noisy;
clean images give much better results.

### 3. Assess — quality score
**What:** scores each page from 0 to 100 for clarity
(clear / blurry / very blurry).
**Why:** the score decides how much help the page needs from the AI model.

### 4. Route — pick the AI model
**What:** sends each page to a small, medium or large AI model based on its
score.
**Why:** cost control — clear pages use the cheap model, only hard pages pay
for the strong one.

### 5. Extract — AI data extraction
**What:** the AI reads each page and pulls out the fields, each with a
confidence score.
**Why:** this is the step that turns pixels into structured data.

### 6. Output — results
**What:** writes the page images and a `result.json` with everything found
per page.
**Why:** one place with the full story of each page — data, quality, model
and errors.

---

## What you get

- **Structured JSON** — per page: fields + confidence scores.
- **Full trace per page** — quality score, tier, and which model read it.
- **Cleaned page images** — handy for review or audit.
- **Reliable batch runs** — a summary at the end: how many documents
  succeeded, how many failed and why.

## Web UI (three steps)

```
python app.py        →    http://127.0.0.1:8000
```

One page: **upload** a PDF → **process** it → **view** the extracted data
(page image, quality score, model, and a Field / Value / Confidence table for
every page).

## How to run

```
python main.py        # process all PDFs in data/input
python main.py file.pdf   # process one specific PDF
python app.py         # web UI at http://127.0.0.1:8000
```

All settings (API key, models, folders) live in the `.env` file.
