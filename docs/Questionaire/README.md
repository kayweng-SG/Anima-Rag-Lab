# Questionnaire source folder

**Canonical path:** `docs/Questionaire/`  
（Cursor 引用 `@/doc/questionnaire/` 时指向此目录；文件夹名保留历史拼写 `Questionaire`。）

Owner-supplied instruments and scoring references for **WBS 0.4** (Module B behavior).  
Archived copies + machine-readable extracts live under:

`data/raw/module_b_behavior/cbarq_mcpq_r/`

---

## File index

| File | Type | Role | Archived to |
|------|------|------|-------------|
| `C-BARQ short version scoring method.pdf` | Scoring | **C-BARQ42** 14 分量表完整公式 | `scoring_methods/C-BARQ_short_version_scoring_method.pdf` |
| `C-BARQ(101) scoring method.PDF` | Scoring | C-BARQ(101) 定义 + **仅 4/14** 公式 | `scoring_methods/C-BARQ_101_scoring_method.pdf` |
| `CBARQ_short-final_copy.pdf` | Form | Serpell 2018 短版问卷正文（~42 题） | `forms/CBARQ_short_questionnaire_2018.pdf` |
| `dog-aggression-questionnaire.pdf` | Form | Serpell 2015 **101 题**完整 C-BARQ 问卷 | `forms/CBARQ_101_questionnaire_2015.pdf` |
| `51Q-Selection_of_Appropriate_Dogs_to_Be_Therapy_Dogs_U.pdf` | Paper | Sakurama et al. 2023 (OA) 治疗犬 51 题因子分析 | `pdfs/` + `therapy_dog_51q_factors.json` |
| `51Q-日本防護犬 51問題與因子14.pdf` | Summary | 同上 51 题 × 14 因子 **中文对照表** | `therapy_dog_51q_zh.json` |
| `DPQ-forms-and-scoring-keys.pdf` | Related | DPQ 长/短表 + 计分键（非 C-BARQ） | `related_instruments/` |
| `Pet function research.pptx` | Notes | 产品研究 PPT；**未复制**到 `data/raw`（体积大） | — |

---

## Machine-readable extracts

| JSON | Contents |
|------|----------|
| `norms_and_scoring.json` | C-BARQ42 / C-BARQ(101) 计分规则 |
| `therapy_dog_51q_factors.json` | 治疗犬 14 因子（英文，含均值/载荷） |
| `therapy_dog_51q_zh.json` | 治疗犬 51 题中文题面 |
| `related_instruments/dpq_scoring.json` | DPQ 长/短表因子 item 映射 |

---

## Gaps (updated 2026-08-13)

- **C-BARQ(101)**：Serpell 计分 PDF 仍只有 4 条官方公式；其余 10 条已用 Duffy & Serpell (2012) Table 3 题面与 2015 问卷编号对齐，写入 `data/raw/.../norms_and_scoring.json`。
- **MCPQ-R**：无独立空白问卷 PDF；Ley 2008/2009 提供 26 形容词 + POMP 计分（已提取）。

---

## Rights

Serpell C-BARQ forms © University of Pennsylvania. MCPQ-R © Ley / Monash publications. Lab use = research ingest staging only.
