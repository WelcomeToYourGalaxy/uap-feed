# uap-feed

Unidentified aerial and anomalous phenomena, unidentified submerged objects, and the question of
non-human intelligence — worldwide, in 25 languages.

`harvest_uap.py` runs every two hours in GitHub Actions, reads 53 wires, refuses the esoteric,
grades what remains by standing and evidence, tags it by subject and region, and writes
`wire_uap.json`. `index.html` loads that file and renders it.

Nothing here rewrites a headline. Titles and snippets are the publishers' own, truncated but never
reworded, and every row keeps its original link. No model in the pipeline, no API key, no paid
service, no dependencies beyond the Python standard library.

## Two judgements, kept separate

This subject carries more noise than almost any other, so the harvester grades rather than
guesses, and it never merges the two questions that matter.

**Standing — who is speaking.** Every wire is labelled and every row carries the label.

| Standing | What it covers |
|---|---|
| Official | AARO, defence departments, national archives, released records |
| Science | Journals, preprints, research programmes |
| Press | General news, 25 language editions |
| Specialist | Independent reporting devoted to this beat |
| Sceptical | The work of explaining cases — a case resolved is a case answered |

Standing is provenance. It is not a claim that a story is true.

**Evidence — what they brought.** Scored per story:

| Signal | Worth |
|---|---|
| Released document or FOIA record | 2 |
| Sensor data — radar, infrared, sonar, telemetry | 2 |
| Hearing, journal or other on-the-record setting | 1 |
| Named witness or sworn testimony | 1 |
| A resolved explanation | 1 |
| Primary source (official or science wire) | 1 |

At **3** or more a row is marked documented, and the Evidence filter narrows to those. The pips on
each row show the score and the words beside them say what earned it.

## What is refused

Claims that cannot be examined are dropped at the door and counted: channelled messages, galactic
federations, reptilians, starseeds, Pleiadians, ancient astronauts, hypnotic regression, predicted
disclosure dates, Nibiru, chemtrails and the rest of the conspiracy furniture.

The word *alien* is refused in its other senses too — immigration law, invasive species, and the
film franchise — which otherwise flood a feed like this with deportation notices and box-office
returns.

Serious independent journalism is welcome. Sceptical work is welcome and labelled as such. The
status line reports how many stories each harvest refused.

## Files

| File | Path in repo | What it is |
|---|---|---|
| `index.html` | `/index.html` | The feed page. Pages serves the repo root, so it must carry this name. |
| `harvest_uap.py` | `/harvest_uap.py` | The harvester. Self-contained. |
| `sources_uap.json` | `/sources_uap.json` | The wire list, with each wire's standing. |
| `wire_uap.json` | `/wire_uap.json` | The output the page reads. Empty placeholder until the first run. Never hand-edit. |
| `uap-feed-weebly-embed.html` | `/uap-feed-weebly-embed.html` | The page wrapped for a Weebly Embed Code element. Regenerate after changing `index.html`. |
| `README.md` | `/README.md` | This file. |
| `harvest.yml` | `/.github/workflows/harvest.yml` | Runs every two hours at :53 and commits the wire. |

## Setup

1. Push these files to the repository root.
2. Settings → Actions → General → Workflow permissions → **Read and write permissions**, save.
3. Actions tab → **Harvest the UAP wire** → *Run workflow*.
4. Settings → Pages → **Deploy from a branch**, branch `main`, folder `/ (root)`.
5. Confirm `https://raw.githubusercontent.com/WelcomeToYourGalaxy/uap-feed/main/wire_uap.json`
   loads in a browser.

If the repository is named something other than `uap-feed`, change `REPO` near the top of the feed
script in `index.html` to match, then regenerate the embed.

## Sources

**Official** — AARO, US Department of Defense releases, NASA, The Black Vault document archive.

**Science** — arXiv UAP and technosignature queries, the Scientific Coalition for UAP Studies, Avi
Loeb, Nature news, Scientific American.

**Specialist** — The Debrief, Liberation Times.

**Sceptical** — Metabunk, Skeptical Inquirer.

**Press** — Space.com, Ars Technica, and Google News editions in English (US, UK, India, Australia,
Canada, South Africa), Spanish (Spain, Mexico, Chile), Portuguese, French, German, Italian, Dutch,
Swedish, Greek, Polish, Russian, Ukrainian, Turkish, Arabic, Hebrew, Persian, Hindi, Indonesian,
Vietnamese, Thai, Japanese, Chinese (simplified and traditional), Korean. Each query is written in
that language.

**Evidence searches** — seven searches aimed at documents rather than commentary: hearings and
oversight, FOIA and declassification, sensor and imagery, scientific study, explanations and
debunks, other governments' programmes, and programmes and funding.

## Filters

Subject (ten), Region (by the ground the story concerns, ten buckets plus *No single region*),
Standing, Evidence, Language, and Window — 24 hours, 7 days, 30 days, older than 30 days, or
everything from the 45-day archive.

## Running it locally

```bash
python3 harvest_uap.py              # full run
python3 harvest_uap.py --dry-run    # harvest and report, write nothing
python3 harvest_uap.py --fixtures tests/
```

Python 3.9 or later.
