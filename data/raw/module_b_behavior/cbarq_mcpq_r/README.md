# 0.4 C-BARQ & MCPQ-R

**Status (2026-08-12):** `docs/Questionaire/` 业主问卷包已索引并归档。

## Source of truth (owner folder)

→ [`docs/Questionaire/README.md`](../../../docs/Questionaire/README.md)

## Archive layout

| Path | Contents |
|------|----------|
| `scoring_methods/` | Serpell 计分说明 + 治疗犬 51Q 中英文摘要 |
| `forms/` | C-BARQ42 / C-BARQ101 问卷正文 PDF |
| `pdfs/` | OA 验证/应用文献 |
| `related_instruments/` | DPQ（相关犬性格量表，非 MCPQ-R） |
| `*.json` | 机器可读计分与因子表 |

## Key JSON

- `norms_and_scoring.json` — C-BARQ42 完整公式；101 仅 4 条
- `therapy_dog_51q_factors.json` — Sakurama 2023 英文因子+常模趋势
- `therapy_dog_51q_zh.json` — 51 题中文题面（14 因子）
- `related_instruments/dpq_scoring.json` — DPQ 计分键

## Remaining gaps

- C-BARQ(101) 其余 10 个分量表公式
- MCPQ-R 官方计分/题目 PDF
