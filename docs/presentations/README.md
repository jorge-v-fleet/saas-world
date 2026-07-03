# Presentations

- `saas-world.md` — overview deck (source of record): what the repo is, the problem, the system +
  per-subsystem slides, how to work with it, rollout examples. Diagrams are ASCII stand-ins so the
  markdown reads on its own / on GitHub.
- `saas-world.html` — the deck to present, generated from the markdown. Styled after
  [jorgeviz.me](https://jorgeviz.me) (Lora serif, light, minimal) with hand-laid-out HTML/CSS
  diagrams in place of the ASCII blocks. Uses [reveal.js](https://revealjs.com) from CDN for
  navigation (needs internet on first open).
- `build.py` — regenerates the HTML from the markdown (swaps the ```diagram-system` /
  ```diagram-npc` blocks for the CSS diagrams). No Node required.

```bash
python3 docs/presentations/build.py     # -> rewrites saas-world.html from saas-world.md
open docs/presentations/saas-world.html  # arrows/space to navigate, Esc = overview, F = fullscreen
```
