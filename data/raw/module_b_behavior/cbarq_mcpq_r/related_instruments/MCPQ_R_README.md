# MCPQ-R (Monash Canine Personality Questionnaire–Revised)

**Status:** No separate Monash “blank form” PDF located. Working pack = Ley journal PDFs + extract below.

## Sources on disk

| File | Role |
|------|------|
| `../pdfs/ley_2008_mcpq_refinement_validation.pdf` | Table 1 adjectives + POMP scoring rule |
| `../pdfs/ley_2009_mcpq_r_reliability.pdf` | Reliability; confirms 26-item / 5 dimensions |
| `mcpq_r_scoring.json` | Machine-readable adjective→dimension map |

## Scoring (Ley 2008)

1. Rate each adjective 1–6 (“really doesn’t describe” → “really describes”).
2. For each dimension: `pct = 100 * sum(scores) / (n_items * 6)`.

## 26 adjectives (MCPQ-R)

- **Extraversion (6):** Active, Energetic, Excitable, Hyperactive, Lively, Restless  
- **Motivation (5):** Assertive, Determined, Independent, Persevering, Tenacious  
- **Training Focus (6):** Attentive, Biddable, Intelligent, Obedient, Reliable, Trainable  
- **Amicability (5):** Easy going, Friendly, Non-aggressive, Relaxed, Sociable  
- **Neuroticism (4):** Fearful, Nervous, Submissive, Timid  

DOI: [10.1016/j.applanim.2008.09.009](https://doi.org/10.1016/j.applanim.2008.09.009)

| `mcpq_r_blank_form.json` | Lab-derived blank (26 items); **not** an official Monash PDF |

