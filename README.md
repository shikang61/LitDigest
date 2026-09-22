# LitDigest

A reading list you have no time for, turned into something you can work through.

Point it at a spreadsheet of arXiv titles and it gives you a card grid. Click a
card and it reads the paper for you and answers the only question that matters
first — *is this worth your evening?* — then the mechanism behind it, then the
equation, then the figures. You can argue with it afterwards.

It does not write summaries. A summary tells you what is in a paper; it does not
tell you whether to read it. Each card opens with a claim, a 1–5 score, and a
verdict that names the one section worth ten minutes if the answer is no.

## Setup

```bash
pip install -r requirements.txt
brew install poppler                     # pdftotext
cp .env.example .env                     # then put your key in it
```

`.env`:

```
XAI_API_KEY=xai-...
GROK_MODEL=grok-4.7                      # the reading. quality matters here
GROK_UTIL_MODEL=grok-4.20-0309-non-reasoning   # bulk classification. speed matters here
```

Two models on purpose: a reasoning model spends its entire token budget thinking
about 182 titles at once and never reaches the JSON, so clustering uses a fast
one. Run `./run.py models` to see what your key can reach.

The spreadsheet defaults to `~/Desktop/LitFeed Literature.xlsx`, with `Num`,
`Title` and `Notes` columns on row 3. Override with `LITDIGEST_XLSX=...`.

## First run

```bash
./run.py all        # read the sheet, resolve every title on arXiv, cluster them
```

About ten minutes, almost all of it arXiv's three-second rate limit. Nothing is
generated yet — that happens when you click.

## Launching it

```bash
./make_app.sh ~/Desktop      # build the app, and drop a copy on the Desktop
```

Then double-click **LitDigest.app**. It starts the server, waits for it, and
opens your browser. Closing the app stops the server.

The bundle records the project's absolute path, so **rebuild it after moving the
project**. The copy itself can live anywhere — Desktop, Dock, `/Applications`.

### If the project lives in ~/Desktop, ~/Documents or ~/Downloads

macOS will not let a double-clicked app read anything in those folders, and an
app with no window never gets the chance to ask for permission — left alone it
fails silently, with `open` reporting success and nothing happening. Running the
same launcher from a terminal works, because your terminal already holds that
permission, which makes it a confusing thing to debug.

So the app checks whether it can actually read `launch.sh`, and if it cannot, it
hands the job to Terminal, which can. Everything works; a Terminal window appears
alongside the browser and has to stay open while you use the app. Keeping the
project anywhere else (`~/LitDigest`, say) avoids the window entirely.

`cache/app.log` records what the app did on its last direct launch.

A double-clicked app gets a bare `PATH`, so the interpreter that has the packages
is recorded in `.python-path` when you set up. If you move to a different Python,
rewrite that file (or set `LITDIGEST_PYTHON`).

`./run.py serve` does the same thing from a terminal.

## Using it

- **Click a card.** It fetches the PDF if it has not already, then streams back
  claim / score / verdict / the trick / holds up.
  It takes about a minute, because the model thinks for most of it before writing
  anything. So the wait shows real progress: the phase it is in, seconds elapsed
  against how long your last runs actually took, and the model's own reasoning
  as it arrives. When the answer starts, the sections fill in as they are written.
- **Go deeper.** A second, longer pass: what you need to know already, the
  mechanism step by step, the central equation rendered from the paper's own
  LaTeX source (with the authors' macros, so it renders correctly), the symbols,
  the limits, and how you would use it. Figures are cropped out of the PDF and
  shown underneath.
- **Ask this paper.** The box sits at the foot of the card, in reach at any point
  in the digest. Questions are answered against the paper's actual text, and the
  conversation is kept per paper.
- **Rewrite it.** Two buttons on every card: one rewrites the summary, the other
  reads it deeply again. Worth using on anything written before a change to how
  the digests are worded — `./run.py warm --force` does the same to all of them,
  which is an overnight job at roughly five minutes a paper.
- **Star it.** The star on a card fills that paper's Title cell yellow in your
  spreadsheet — the same yellow you were already using by hand. Starred papers
  sort to the front and have their own filter.
- **Write a note.** The note box in the open card writes straight into the Notes
  column. Your existing notes are there when you open a paper.

Everything is cached per paper in `cache/papers/NNNN.json`, so nothing is ever
generated twice unless you ask for it.

## Commands

```
./run.py all         read the sheet, match on arXiv, cluster            (~10 min)
./run.py serve       the app                          --port 8000
./run.py warm        pre-generate glances for every paper, in parallel  (optional)
./run.py status      what is done, what failed, which titles arXiv could not find
./run.py models      model ids your key can reach

./run.py ingest      spreadsheet -> cache/papers/*.json
./run.py match       title -> arXiv id, abstract, authors
./run.py fetch       arXiv id -> PDF, introduction, conclusion
./run.py taxonomy    all titles -> topic clusters
./run.py topics      file every paper under a cluster
```

Every stage skips papers it already finished, so an interrupted run costs
nothing to restart. `--force` redoes one, `--limit N` tries a handful first.

`warm` is worth starting before bed if you want the whole grid populated; the
app works without it, one click at a time.

## What syncs back to the spreadsheet

Two things, and nothing else:

| in the app | in the spreadsheet |
|---|---|
| the star on a card | the Title cell filled yellow (`FFFFFF00`) |
| the note box | the Notes column for that row |

Both are written the moment you make them, matched by the `Num` column. Existing
yellow cells and existing notes are read back in, so the highlighting you already
did shows up as stars on first run. The first write of each session copies the
untouched file to `cache/backup/` first.

Everything else — verdicts, scores, the digests themselves — stays in
`cache/papers/` and never touches your sheet.

## Categories

Papers are filed under five buckets — Fusion, Numerics, AI, Finance,
Econophysics — defined in `CLUSTERS` in `litdigest/config.py`. A paper that spans
two is filed by its own contribution: a new learning method applied to plasma is
AI, a plasma result that uses a trained model is Fusion, a numerical scheme for a
plasma system is Numerics.

To change them, edit that list and delete `cache/taxonomy.json`. Every paper
filed under a category that no longer exists is refiled the next time you open
the app, so you do not have to reclassify anything by hand.

## Adding papers later

Append rows to the spreadsheet and open the app. It re-reads the sheet every
time it starts, files any new papers under a category, and shows them in the
grid; clicking one resolves it on arXiv and fetches the PDF then and there.
**Reload sheet** does the same without restarting.

Editing a title discards that paper's cached work so it is redone. Your triage
mark survives, since titles are often edited just to fix a typo.

If arXiv cannot find a paper — usually because it was retitled between versions
beyond recognition — pin it by hand:

```bash
./run.py pin 121 2607.28762v2
```

## How it fits together

```
run.py                 CLI
server.py              FastAPI: card grid, streaming generate, triage, export
web/index.html         the whole frontend, one file
litdigest/config.py    paths, models, rate limits, .env loader
litdigest/store.py     one JSON file per paper
litdigest/ingest.py    spreadsheet -> records
litdigest/arxiv.py     title -> arXiv entry, fuzzy-scored with fallbacks
litdigest/extract.py   PDF -> introduction and conclusion
litdigest/latex.py     arXiv source -> real equations and author macros
litdigest/figures.py   PDF -> cropped figure images
litdigest/generate.py  the glance / deep / ask prompts, streamed
litdigest/llm.py       xAI client, clustering
launch.sh              starts the server and opens the browser
make_app.sh            builds LitDigest.app for wherever the project lives
assets/icon.icns       the app icon
tests/                 offline tests for the matcher, parser and spreadsheet code
```

## Tests

```bash
pip install pytest
python3 -m pytest tests/ -q
```

No network and no model calls. They cover the parts that break quietly: title
matching (including papers retitled between arXiv versions), the tagged-section
parser (including half-written streams), header-row detection, and the rule that
editing a title throws away the digest built from the old one.

## Known limits

- Titles are matched on character similarity first, then on how many of the
  title's words the candidate contains — which is what catches a paper retitled
  between arXiv versions. Anything still unresolved is listed by `status` rather
  than guessed at, and can be pinned by hand.
- A glance takes about a minute because the reasoning model thinks before it
  writes. The progress bar is driven by the median of your own past runs, so it
  gets more accurate the more you use it. `warm` removes the wait entirely.
- Figure cropping is a heuristic — it takes the drawing region above each
  "Figure N" caption. It is right on normal two-column papers and can clip oddly
  on unusual layouts.
- Only the star and the note are ever written back, and the file is backed up
  before the first write of each session. Saving with openpyxl preserves ordinary
  sheets but will not carry across charts or macros, so keep a copy if your
  workbook has either.
