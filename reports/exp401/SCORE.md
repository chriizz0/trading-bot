# EXP-401 Zwischenstand – KI als Analyst

Stand 2026-10-31

## Claude

**Prognosegüte**

- Prognosen: 60 in 2 Wochen · Trefferquote 45.0% (Ziel ≥ 55 %; Anteil steigender Werte 50%)
- Brier 0.2553 · Münzwurf 0,2500 · immer long 0.2525 · Momentum 0.2375 (kleiner = besser)
- Information Coefficient Ø +0.122 (Permutationstest p = 0.20) · Long-Short kumuliert -1.56 %

**Simulierte Trades** (Tageskerzen, 0,1 % Kosten, keine echte Ausführung – getrennt von der Prognosegüte lesen)

- Trades: 7, Ø +0.04 R, Gewinner 43%

| bin     |   n |     p |    up |
|:--------|----:|------:|------:|
| 0,4–0,5 |  15 | 0.451 | 0.667 |
| 0,5     |  20 | 0.5   | 0.4   |
| 0,5–0,6 |  18 | 0.538 | 0.556 |
| ≤0,4    |   3 | 0.4   | 0.333 |
| ≥0,6    |   4 | 0.6   | 0.25  |

## ChatGPT

**Prognosegüte**

- Prognosen: 40 in 1 Wochen · Trefferquote 63.2% (Ziel ≥ 55 %; Anteil steigender Werte 60%)
- Brier 0.2438 · Münzwurf 0,2500 · immer long 0.2425 · Momentum 0.2350 (kleiner = besser)
- Information Coefficient Ø +0.386 (Permutationstest p = 0.01) · Long-Short kumuliert +3.16 %

| bin     |   n |     p |    up |
|:--------|----:|------:|------:|
| 0,4–0,5 |  23 | 0.474 | 0.478 |
| 0,5     |   2 | 0.5   | 0.5   |
| 0,5–0,6 |  15 | 0.527 | 0.8   |

