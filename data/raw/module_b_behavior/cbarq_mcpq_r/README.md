# 0.4 C-BARQ & MCPQ-R

**Status (2026-08-13):** C-BARQ(101) **14/14** subscale item formulas filled; MCPQ-R adjective + POMP scoring from Ley 2008/2009.

## Source of truth (owner folder)

→ [`docs/Questionaire/README.md`](../../../docs/Questionaire/README.md)

## Archive layout

| Path | Contents |
|------|----------|
| `scoring_methods/` | Serpell 计分说明 + 治疗犬 51Q |
| `forms/` | C-BARQ42 / C-BARQ101 问卷正文 |
| `pdfs/` | OA 文献（含 Duffy 2012、Ley 2008/2009、Hsu 2003） |
| `related_instruments/` | DPQ + **MCPQ-R** 计分提取 |
| `norms_and_scoring.json` | 机器可读完整计分 |

## How the 10 missing C-BARQ(101) formulas were filled

Serpell’s own 101 scoring PDF only lists 4 subscales. The other 10 were reconstructed by matching **Duffy & Serpell (2012) Table 3** item stems to the **2015 101-item form** numbering, then cross-checked against the 4 official formulas.

Source PDF: `pdfs/duffy_serpell_2012_cbarq_subscale_items.pdf`

## MCPQ-R

See `related_instruments/MCPQ_R_README.md` — 26 adjectives + POMP `%` scoring. No blank Monash form PDF found; Ley papers are the operable source.

## Remaining caveats

- Item **51** duplicates the “stepped over” stem of item **30**; score under owner-directed only (Duffy lists once).
- Some stems appear in both aggression and fear sections (different item numbers) — map per section as in JSON.
