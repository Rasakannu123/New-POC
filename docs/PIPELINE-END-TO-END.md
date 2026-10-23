# Document Extraction Pipeline — Start to End

> Input folder (`data/input/*.pdf`) → Output folder (`data/output/<name>/`)
> One document, followed all the way through, with example data at every step.
> Example document used throughout: **`BRIGHT PHARMACY-5.pdf`** (1 page) → document ID **`0010`**.

---

## 0. The 30,000-foot view

```
data/input/*.pdf
   │
   ▼
main.py ──► run() ──► run_async()                          [pipeline_graph.py:565]
   │                       │
   │                       ├── identity:  allocate_document_id()  → "0010"
   │                       ├── budgets:   TokenBudget + RetryBudget
   │                       ├── latency:   LatencyTracker (per node thresholds)
   │                       │
   │                       ▼
   │              DOCUMENT GRAPH  (per PDF, max 4 documents at once)
   │              convert ──────► pages ──────► output ──────► END
   │                              │
   │                              ▼
   │              PAGE GRAPH  (per page, all pages concurrently)
   │              enhance ──► assess ──► route ──► extract ──► END
   │
   ▼
data/output/BRIGHT PHARMACY-5/
   ├── page-01.png        (enhanced image)
   └── result.json        (extracted fields + metadata)
```

---

## 1. First: the three objects that confuse everyone

| Object | What it IS | Analogy | Created | Lifetime |
|---|---|---|---|---|
| **`DocumentContext`** (`ctx`) | a **dataclass** — the *tool kit + shared counters* of one document | the worker: carries tools, ID badge, budgets | once per document, in `process_one` | whole document run |
| **`DocumentState`** | a **TypedDict** — the *mailbox* of the document graph | the tray passed between the 3 document stages | new dict at every `ainvoke` step | one graph step to the next |
| **`PageState`** | a **TypedDict** — the *mailbox* of the page graph | the tray passed between the 4 page stages | new dict at every page-graph step | one page step to the next |

### The rule

- **Context (`ctx`) = tools & shared money counters** → engines, IDs, token/retry budgets, latency tracker, concurrency gates. Long-lived, mutable, **one per document**. Every node receives it inside its state so it can reach the tools.
- **State = data produced by the pipeline** → images, scores, routing, records, output path. Short-lived, **merged node-by-node** (every `return {"key": value}` writes into it).

### Where each is defined and who touches it

```
DocumentContext  (pipeline_graph.py:145)      ← built by DocumentContext.create() (:166)
    pdf_path, document_id "0010"              ← identity.py
    conversion / preprocessing / quality /    ← the 5 feature engines
    router / extractor
    token_budget, retry_budget                ← budget.py
    latency                                   ← latency.py
    gates {enhance:5, assess:3, route:2, extract:4}  ← asyncio.Semaphores
    page_graph                                ← compiled page graph
    page_ids ["0010/01"], page_count 1

DocumentState   (pipeline_graph.py:206)       ← passed to document nodes
    ctx            → the DocumentContext itself (so nodes can reach tools)
    images         → produced by convert_node
    page_results   → produced by pages_node
    output_json    → produced by output_node
    error          → produced by convert_node on failure

PageState       (pipeline_graph.py:190)       ← passed to page nodes
    ctx            → same DocumentContext (shared!)
    page_number 1, page_id "0010/01"
    image          → arrives already rendered (converter ran at document level)
    enhanced_image → produced by enhance_node
    assessment     → produced by assess_node
    routing        → produced by route_node
    record         → produced by extract_node
```

**Key facts that clear the confusion:**

1. `ctx` travels **inside** the states (`state["ctx"]`) — that is how a page node can reach document-wide budgets.
2. States are **merged, not returned around**: `return {"record": ...}` in `extract_node` merges `record` into `PageState`; the caller of the graph gets the final merged dict back from `ainvoke`.
3. `DocumentState` and `PageState` are **two different mailboxes for two different graphs**. The only bridge between them is `pages_node`, which writes page results into `DocumentState["page_results"]`.
4. `DocumentContext` is **never** put into the JSON output — only data from the states is.

---

## 2. The three cross-cutting helpers (used at every step)

### 2.1 Identity — `src/identity.py`

| Method | Key line | Example |
|---|---|---|
| `allocate_document_id()` [:34](../src/identity.py) | `return f"{current:04d}"` | `"0010"` (counter persisted in `data/output/.document_id_counter`) |
| `page_id_for(document_id, n)` [:44](../src/identity.py) | `return f"{document_id}/{page_number:02d}"` | `"0010/01"`, `"0010/02"` |

Work is identified **by ID, never by file name** — file names can repeat (`9997777 (1).pdf`, `9997777 - Copy 1.pdf`), IDs cannot.

### 2.2 Budget — `src/budget.py`

| Budget | Key line | Example |
|---|---|---|
| `TokenBudget.record(in, out)` [:40](../src/budget.py) | `self.used += usage.total_tokens` | call 1: 3084 in + 274 out → `used = 3358` |
| `TokenBudget.exhausted` [:51](../src/budget.py) | `return self.limit > 0 and self.used >= self.limit` | limit 5000, used 3358 → `False` → next page may call the model |
| `RetryBudget.take_retry(page_used)` [:66](../src/budget.py) | `if page_retries_used >= self.page_limit: return False` | ≤ 2 retries per page **and** ≤ 5 per document |

### 2.3 Latency — `src/latency.py`

| Method | Key line | Example |
|---|---|---|
| `LatencyTracker.measure(node, subject)` [:52](../src/latency.py) | `timing.exceeded = timing.threshold > 0 and timing.seconds > timing.threshold` | `convert` took 8.61s vs threshold 120s → status `OK` |
| `subject_total(page_id)` [:71](../src/latency.py) | `sum(t.seconds for t in self.timings if t.subject == subject)` | `"0010/01"` total → `167.03` |
| `node_totals()` / `total()` [:77](../src/latency.py) | sums per node / overall | `{"convert": 8.61, "enhance": 35.6, ...}` / `176.11` |

---

## 3. The walk — input folder to output folder

### STEP 0 — trigger

```
python main.py                        (or: python main.py "data/input/BRIGHT PHARMACY-5.pdf")
   │
   ▼
main.py:24  files = [Path(arg) for arg in sys.argv[1:]] or None
   │        → None means "take every PDF in data/input"
   ▼
main.py:26  sys.exit(run(files))
   │
   ▼
pipeline_graph.py:627  def run(...)  →  return asyncio.run(run_async(pdf_files))
```

**Example input:** no arguments → `files = None`
**Example output:** runs to completion, shell gets exit code `0`

---

### STEP 1 — `run_async` receives the run

```
run_async(None)                                  [pipeline_graph.py:565]
   │ ① console.install()                         → aligned log format
   │ ② INPUT_DIR / OUTPUT_DIR mkdir               → data/input, data/output exist
   │ ③ pdf_files is None → scan folder            [pipeline_graph.py:576]
   ▼
```

**Example input:** `pdf_files = None`
**Example output:** `pdf_files = [AL TAHER - 21542 1.pdf, BRIGHT PHARMACY-5.pdf, ...]` (sorted)

---

### STEP 2 — build the document graph ONCE (wiring, not running)

```
graph = build_document_graph().compile()         [pipeline_graph.py:588]
   │  add_node("convert", convert_node)
   │  add_node("pages",   pages_node)
   │  add_node("output",  output_node)
   │  edges: START → convert → pages → output → END
   ▼
document_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOCUMENTS=4)
```

**Example output:** one executable graph object shared by all documents.

---

### STEP 3 — `DocumentContext.create(pdf_path)` per document

```
ctx = DocumentContext.create(pdf_path)           [pipeline_graph.py:596 → :166]
   │
   ├── document_id = allocate_document_id()      → "0010"   (IDENTITY)
   ├── conversion  = ImageConversionLayer(dpi=300)
   ├── preprocessing = ImagePreprocessingEngine()
   ├── quality     = QualityAssessmentEngine()
   ├── router      = ModelRouter()
   ├── extractor   = ExtractionEngine()          (locked to template fields)
   ├── token_budget = TokenBudget(5000)          (BUDGET)
   ├── retry_budget = RetryBudget(2, 5)          (BUDGET)
   ├── latency     = LatencyTracker(thresholds)  (LATENCY)
   ├── gates       = {enhance:5, assess:3, route:2, extract:4}   (concurrency)
   └── page_graph  = build_page_graph().compile()
   ▼
```

**Example input:** `pdf_path = data/input/BRIGHT PHARMACY-5.pdf`
**Example output:** `ctx` with `document_id="0010"`, `token_budget.used=0`, `retry_budget.retries_used=0`, empty `latency.timings`
**Console:**
```
11:47:54 | 0010 | document | STARTED | | BRIGHT PHARMACY-5.pdf
```

---

### STEP 4 — Feature 1: `convert_node` (PDF → page images)

```
state = await graph.ainvoke({"ctx": ctx})        [pipeline_graph.py:600]
   │
   ▼
convert_node(state)                              [pipeline_graph.py:218]
   │  with ctx.latency.measure("convert", "0010")        ← LATENCY starts
   │  converted = ctx.conversion.convert_pages(pdf_path)  [conversion.py:55]
   │      pages = convert_from_path(pdf, dpi=300)         [conversion.py:64]
   │
   │  ctx.page_ids = [page_id_for("0010", 1)]             ← IDENTITY
   │      → ["0010/01"]
   │  return {"images": converted.pages}                  → merges into DocumentState
   ▼
```

**Example input:** `BRIGHT PHARMACY-5.pdf`
**Example output:** `state["images"] = [<PIL.Image 2480x3508 RGB>]`, `ctx.page_ids = ["0010/01"]`
**Console:**
```
11:48:03 | 0010 | convert | OK | latency 8.61s (threshold 120.0s) | PDF-to-Images converter; 1 page
```
Failure path: a broken PDF returns `{"error": "Invalid or unreadable PDF: ..."}` — the run continues, this document is reported `FAILED` at the end.

---

### STEP 5 — `pages_node`: fan-out to the page graph

```
pages_node(state)                                [pipeline_graph.py:389]
   │  images = state["images"]
   │
   │  for every page N: process_page(N)                  [pipeline_graph.py:396]
   │      │  if ctx.token_budget.exhausted:              ← BUDGET guard
   │      │      record = _blank_record(...) + error "Token limit has been reached..."
   │      │  page_state = await ctx.page_graph.ainvoke({ctx, page_number, page_id, image})
   │      ▼
   │  results = await asyncio.gather(process_page(1), process_page(2), ...)  ← ALL PAGES AT ONCE
   │  return {"page_results": [(record, image), ...]}    → merges into DocumentState
   ▼
```

**Example input:** `state["images"] = [<img>]`, `ctx.page_ids = ["0010/01"]`
**Example output (after the page graph below):** `{"page_results": [({...record...}, <enhanced img>)]}`

---

### STEP 6 — Feature 2: `enhance_node` (image cleanup)

```
enhance_node(state)                              [pipeline_graph.py:253]
   │  async with ctx.gates["enhance"]                    ← concurrency gate (5 pages max)
   │  with ctx.latency.measure("enhance", "0010/01")     ← LATENCY
   │  image = ctx.preprocessing.enhance(state["image"])  [preprocessing.py:63]
   │      grayscale → deblur(if Laplacian var < 50) → medianBlur(3)
   │      → deskew(Hough angle, rotate if ≥ 0.3°) → CLAHE
   │  return {"enhanced_image": image}                   → PageState
   ▼
```

**Example input:** `<PIL RGB 2480x3508, skewed 0.8°, slightly blurry>`
**Example output:** `<PIL L 2480x3508, straightened, contrast-boosted>`
```
report.steps_applied = ["grayscale", "deblur(wiener+unsharp)", "denoise(median)",
                        "deskew(+0.80deg)", "contrast(CLAHE)"]
```
**Console:**
```
11:48:32 | 0010/01 | enhance | OK | latency 29.19s (threshold 30.0s) | Image enhancement
```

---

### STEP 7 — Feature 3: `assess_node` (quality score)

```
assess_node(state)                               [pipeline_graph.py:269]
   │  async with ctx.gates["assess"]                     ← 3 pages max
   │  result = ctx.quality.assess(state["enhanced_image"])  [quality.py:67]
   │      score = mean OCR confidence × coverage          [quality.py:129-133]
   │      tier  = clear(>80) / blurry(50-80) / very_blurry(<50)
   │  return {"assessment": {"page_id", "score", "tier"}} → PageState
   ▼
```

**Example input:** `<enhanced image>`
**Example output:** `{"assessment": {"page_id": "0010/01", "score": 83.0, "tier": "clear"}}`
**Console:**
```
11:49:10 | 0010/01 | assess | OK | latency 16.39s (threshold 60.0s) | score 83.0 -> clear
```

---

### STEP 8 — Feature 4: `route_node` (tier → model, local decision)

```
route_node(state)                                [pipeline_graph.py:290]
   │  async with ctx.gates["route"]                      ← 2 pages max
   │  decision = ctx.router.route(assessment)            [router.py:52]
   │      model = tier_model_map.get("clear")            [router.py:56]
   │      → TIER_MODEL_MAP from .env: clear→small, blurry→medium, very_blurry→large
   │  return {"routing": {"page_id", "model", "tier", "score"}} → PageState
   ▼
```

**Example input:** `score 83.0, tier "clear"`
**Example output:** `{"routing": {"page_id": "0010/01", "model": "qwen/qwen3.7-plus:free", "tier": "clear", "score": 83.0}}`
**Console:**
```
11:49:29 | 0010/01 | route | OK | latency 0.00s (threshold 5.0s) | model qwen/qwen3.7-plus:free
```

---

### STEP 9 — Feature 5: `extract_node` (the only model call)

```
extract_node(state)                              [pipeline_graph.py:317]
   │  async with ctx.gates["extract"]                    ← 4 pages max
   │  if ctx.token_budget.exhausted:                     ← BUDGET guard
   │      return {"record": blank + "Token limit has been reached..."}
   │
   │  result = await ctx.extractor.extract(image, decision, retry_budget, subject="0010/01")
   │      payload = base64 PNG, downscaled to ≤2048px    [extraction.py:99]
   │      await client.chat.completions.create(          [extraction.py:103]
   │          model="qwen/qwen3.7-plus:free",
   │          messages=[EXTRACTION_PROMPT + image], max_tokens=1000)
   │      on failure: if not budget.take_retry(page_used): break   ← BUDGET (≤2/page, ≤5/doc)
   │      fields, confidences = _parse_json_object(raw)  [extraction.py:122]
   │
   │  usage = ctx.token_budget.record(3084, 274)          ← BUDGET: used 0 → 3358
   │  with ctx.latency.measure("extract", "0010/01")      ← LATENCY
   │  return {"record": {...}}                            → PageState
   ▼
```

**Example input:** enhanced image + `RoutingDecision(model="qwen/qwen3.7-plus:free", tier="clear", score=83.0)`
**Model raw reply:**
```json
{"document_no": {"value": "W162647", "confidence": 89},
 "date": {"value": "08/02/2023", "confidence": 89},
 "buyer": {"value": "SEVEN SEAS SHIPCHANDLERS L.L.C", "confidence": 89},
 "buyer-trn": {"value": "100569476300003", "confidence": 89},
 "seller": {"value": "BRIGHT PHARMACY", "confidence": 89},
 "seller-trn": {"value": "100288021700003", "confidence": 89},
 "dn": {"value": null, "confidence": 0},
 "sub total": {"value": "2,085.00", "confidence": 89}}
```
**Example output (`state["record"]`):**
```json
{"page": 1, "page_id": "0010/01", "image": "page-01.png", "status": "completed",
 "quality_score": 83.0, "quality_tier": "clear", "model": "qwen/qwen3.7-plus:free",
 "extracted_fields": {"document_no": "W162647", "date": "08/02/2023", "buyer": "SEVEN SEAS SHIPCHANDLERS L.L.C",
                      "buyer-trn": "100569476300003", "seller": "BRIGHT PHARMACY", "seller-trn": "100288021700003",
                      "dn": null, "sub total": "2,085.00"},
 "field_confidence_scores": {"document_no": 89, "date": 89, "buyer": 89, "buyer-trn": 89,
                             "seller": 89, "seller-trn": 89, "dn": 0, "sub total": 89},
 "success": true, "error": null,
 "processing_time": 167.03,
 "token_usage": {"input_tokens": 3084, "output_tokens": 274, "total_tokens": 3358},
 "document_total_tokens": 3358, "retries_used": 0}
```
**Console:**
```
11:49:46 | 0010/01 | extract | OK | latency 55.07s (threshold 120.0s) | completed; tokens 3358 (input 3084, output 274); document total 3358 tokens
```
Page graph now hits `END` (`extract → END`).

---

### STEP 10 — the return journey (page state → document state)

```
return {"record": record}                        [pipeline_graph.py:386]
   │  merges into PageState; page graph ENDS
   ▼
process_page receives the finished page_state    [pipeline_graph.py:420]
   │  return page_state["record"], page_state.get("enhanced_image")
   ▼
asyncio.gather collects ALL pages                [pipeline_graph.py:426]
   │  return {"page_results": [(record, image), ...]}     [pipeline_graph.py:429]
   │  ① dict merges into DocumentState
   │  ② edge "pages" → "output" passes control
   ▼
```

**Example output:** `state["page_results"] = [({...record from step 9...}, <enhanced image>)]`

---

### STEP 11 — Feature 6: `output_node` → `_write_output` (JSON output)

```
output_node(state)                               [pipeline_graph.py:432]
   │  results = state["page_results"]                    ← receives the data HERE
   │  pages  = sorted(records by page number)
   │  images = {page_number: enhanced_image}
   ▼
_write_output(ctx, pages, images)                [pipeline_graph.py:446]
   │  directory = OUTPUT_DIR / "BRIGHT PHARMACY-5"; mkdir
   │  image.save(directory / "page-01.png")               ← enhanced images saved
   │  result.json.write_text(json.dumps({document, document_id, pages}))
   │  return path → state["output_json"]
   │  graph hits END → graph.ainvoke returns the final state
   ▼
```

**Example input:** `pages = [{...record...}]`, `images = {1: <enhanced img>}`
**Example output (the output folder):**
```
data/output/BRIGHT PHARMACY-5/
   ├── page-01.png
   └── result.json   ← {"document": "BRIGHT PHARMACY-5.pdf",
                        "document_id": "0010",
                        "pages": [{...extracted_fields + metadata...}]}
```
**Console:**
```
11:49:50 | 0010 | output | OK | latency 2.65s (threshold 30.0s) | JSON output; 1 page; result.json
```

---

### STEP 12 — back in `process_one`: finalize + report

```
process_one continues                            [pipeline_graph.py:608]
   │  output_json = state.get("output_json", "")         ← path or "" if failed
   │  if output_json:
   │      _finalize(output_json, ctx)                    [pipeline_graph.py:524]
   │          adds total_processing_time = 176.11        ← LATENCY total
   │          adds node_latency = {convert: 8.61, enhance: 35.6, assess: 44.19,
   │                               route: 32.17, extract: 55.07, output: 0.47}
   │          adds token_usage = {limit: 5000, used: 3358, limit_reached: false}   ← BUDGET
   │          adds retry_usage = {page_limit: 2, document_limit: 5, retries_used: 0}
   │          stamps total_processing_time on every page record
   │  _report_latency(ctx)                               [pipeline_graph.py:550]
   │  console.emit(... "SAVED", output_json)
   │  return True
   ▼
run_async counts results → return 0 → main.py: sys.exit(0)
```

**Console:**
```
11:49:50 | 0010 | summary | COMPLETED | latency 176.11s (document total) | node times: convert 8.61s; enhance 35.60s; assess 44.19s; route 32.17s; extract 55.07s; output 0.47s
11:49:50 | 0010 | result  | SAVED     | | data/output/BRIGHT PHARMACY-5/result.json
...
11:50:12 | run  | summary | COMPLETED | | 2 succeeded, 0 failed
```

---

## 4. Final result.json (real example)

```json
{
  "document": "BRIGHT PHARMACY-5.pdf",
  "document_id": "0010",
  "pages": [
    {
      "page": 1,
      "page_id": "0010/01",
      "image": "page-01.png",
      "status": "completed",
      "quality_score": 83.0,
      "quality_tier": "clear",
      "model": "qwen/qwen3.7-plus:free",
      "extracted_fields": {
        "document_no": "W162647",
        "date": "08/02/2023",
        "buyer": "SEVEN SEAS SHIPCHANDLERS L.L.C",
        "buyer-trn": "100569476300003",
        "seller": "BRIGHT PHARMACY",
        "seller-trn": "100288021700003",
        "dn": null,
        "sub total": "2,085.00"
      },
      "field_confidence_scores": {
        "document_no": 89, "date": 89, "buyer": 89, "buyer-trn": 89,
        "seller": 89, "seller-trn": 89, "dn": 0, "sub total": 89
      },
      "success": true,
      "error": null,
      "processing_time": 167.03,
      "token_usage": {"input_tokens": 3084, "output_tokens": 274, "total_tokens": 3358},
      "document_total_tokens": 3358,
      "retries_used": 0,
      "total_processing_time": 176.11
    }
  ],
  "total_processing_time": 176.11,
  "node_latency": {"convert": 8.61, "enhance": 35.6, "assess": 44.19, "route": 32.17, "extract": 55.07, "output": 0.47},
  "token_usage": {"limit": 5000, "used": 3358, "limit_reached": false},
  "retry_usage": {"page_limit": 2, "document_limit": 5, "retries_used": 0}
}
```

---

## 5. Where identity / budget / latency appear at each step

| Step | IDENTITY | BUDGET | LATENCY |
|---|---|---|---|
| STEP 3 context create | `allocate_document_id()` → `"0010"` | `TokenBudget(5000)`, `RetryBudget(2,5)` created | `LatencyTracker` created |
| STEP 4 convert | `page_id_for()` → `"0010/01"` | — | `measure("convert", "0010")` |
| STEP 5 pages | each task uses `ctx.page_ids[N-1]` | `token_budget.exhausted` guard before every page | — |
| STEP 6-8 enhance/assess/route | subject = `"0010/01"` | — | `measure("enhance"/"assess"/"route", "0010/01")` |
| STEP 9 extract | subject = `"0010/01"` | `take_retry()`, `token_budget.record()` | `measure("extract", "0010/01")` |
| STEP 11 output | `"document_id": "0010"` into result.json | — | `measure("output", "0010")` |
| STEP 12 finalize | page_id already in every record | `token_usage` + `retry_usage` blocks | `total_processing_time`, `node_latency`, `subject_total()` |

---

## 6. One-page cheat sheet

```
data/input/BRIGHT PHARMACY-5.pdf
   │  run() → run_async()                       [sync → async bridge]
   │  DocumentContext.create()                  → ctx (ID "0010", engines, budgets, gates)
   │  graph.ainvoke({"ctx": ctx})
   │
   ├─ convert_node   : PDF → [<img>]            page IDs "0010/01"
   ├─ pages_node     : gather all pages
   │    └─ page graph per page (concurrent):
   │         enhance_node : cleanup image
   │         assess_node  : score 83.0 → "clear"
   │         route_node   : model "qwen/qwen3.7-plus:free"
   │         extract_node : fields {document_no: "W162647", ...}   tokens 3358
   ├─ output_node    : page-01.png + result.json
   │
   ├─ _finalize      : totals into result.json
   ├─ _report_latency: console summary
   └─ return 0 → sys.exit(0)

data/output/BRIGHT PHARMACY-5/
   ├── page-01.png
   └── result.json
```
