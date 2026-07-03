#!/usr/bin/env python3
"""Render the markdown deck to a self-contained reveal.js HTML page styled after jorgeviz.me.
Swaps the ```diagram-system / ```diagram-npc ASCII blocks for hand-laid-out HTML/CSS diagrams."""
import re, pathlib

src = pathlib.Path("docs/presentations/saas-world.md").read_text()
if src.startswith("---"):
    src = src.split("---", 2)[2]
src = re.sub(r"<!--\s*_?paginate.*?-->", "", src).strip()

# ---- HTML diagrams (kept blank-line-free so marked treats each as one HTML block) ----
SYSTEM = (
'<div class="diag diag-system">'
  '<div class="band"><span class="band-label">build-time &middot; all randomness resolved offline</span>'
    '<div class="row">'
      '<div class="node"><b>Data Substrate</b><small>world &middot; personas &middot; templates</small></div>'
      '<span class="arr">&rarr;</span>'
      '<div class="node"><b>Seeding Engine</b><small>sample &rarr; bind &rarr; assemble &rarr;<br>project-eval &rarr; gate &rarr; freeze</small></div>'
      '<span class="arr">&rarr;</span>'
      '<div class="node"><b>Frozen Instance</b><small>seed &middot; overlay &middot; timeline &middot; eval + hash</small></div>'
    '</div>'
  '</div>'
  '<div class="loads"><span class="down">&darr;</span> loads unchanged</div>'
  '<div class="band"><span class="band-label">runtime &middot; deterministic &middot; consumes the instance as-is</span>'
    '<div class="row">'
      '<div class="node soft"><b>Agent</b></div>'
      '<span class="arr">&rarr;</span>'
      '<div class="node"><b>Tool API</b><small>action space</small></div>'
      '<span class="arr">&rarr;</span>'
      '<div class="node hub"><b>KERNEL</b><small>single writer<br>+ event queue</small></div>'
      '<div class="col side">'
        '<div class="bi"><span class="arr">&harr;</span><div class="node soft"><b>World State</b></div></div>'
        '<div class="bi"><span class="arr">&harr;</span><div class="node soft"><b>NPC Engine</b><small>rule core + LLM parser</small></div></div>'
      '</div>'
    '</div>'
    '<div class="loads"><span class="down">&darr;</span> every event appended</div>'
    '<div class="row">'
      '<div class="node soft"><b>Trajectory Store</b></div>'
      '<span class="arr">&rarr;</span>'
      '<div class="node soft"><b>Evaluator</b><small>deterministic predicates</small></div>'
      '<span class="arr">&rarr;</span>'
      '<div class="node soft"><b>Operator CLI / Inspector</b></div>'
    '</div>'
  '</div>'
'</div>'
)

NPC = (
'<div class="diag diag-npc"><div class="row">'
  '<div class="node soft"><b>agent free-text</b><small>message</small></div>'
  '<span class="arr">&rarr;</span>'
  '<div class="node"><b>LLM parser</b><small>text &rarr; fixed intent</small></div>'
  '<span class="arr">&rarr;</span>'
  '<div class="node hub"><b>decision core</b><small>deterministic<br>scoped view + goals</small></div>'
  '<span class="arr">&rarr;</span>'
  '<div class="col">'
    '<div class="node soft"><b>world effect via Kernel</b><small>e.g. reveal blocker</small></div>'
    '<div class="node soft"><b>reply in voice</b><small>@ now + delay</small></div>'
  '</div>'
'</div></div>'
)

SHOTS = (
'<div class="shots">'
  '<figure><img src="score-inspector.png" alt="score breakdown"><figcaption>score</figcaption></figure>'
  '<figure><img src="traj-timeline.png" alt="trajectory timeline"><figcaption>trajectory timeline</figcaption></figure>'
  '<figure><img src="rollout-distro.png" alt="rollout distribution"><figcaption>distribution</figcaption></figure>'
'</div>'
'<p class="inspector-link">explore any run live &rarr; <a href="http://127.0.0.1:8092/inspector">127.0.0.1:8092/inspector</a></p>'
)

src = re.sub(r"```diagram-system\n.*?\n```", lambda m: SYSTEM, src, flags=re.S)
src = re.sub(r"```diagram-npc\n.*?\n```", lambda m: NPC, src, flags=re.S)
src = re.sub(r"```shots\n.*?\n```", lambda m: SHOTS, src, flags=re.S)
md = src.replace("</textarea>", "<\\/textarea>")

html = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>saas-world &middot; Jorge Vizcayno</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,500;0,600;1,400;1,500&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5.1.0/dist/reveal.css">
<style>
  :root{ --ink:#111; --ink2:#222; --mut:#555; --mut2:#666; --faint:#bbb; --line:#e4e4e4; --paper:#fff; }
  html,body{ background:var(--paper); }
  .reveal{ font-family:'Lora',Georgia,serif; color:var(--ink); font-weight:400; font-size:30px; }
  .reveal .slides{ text-align:left; }
  .reveal .slides section{ padding:0 8px; }
  .reveal h1,.reveal h2,.reveal h3{ font-family:'Lora',Georgia,serif; font-weight:500; letter-spacing:-0.01em; color:var(--ink); text-transform:none; }
  .reveal h1{ font-size:2.4em; }
  .reveal h2{ font-size:1.55em; margin:0 0 0.6em; padding-bottom:0.3em; border-bottom:1px solid var(--line); }
  .reveal h3{ font-size:0.86em; font-weight:400; font-style:italic; color:var(--mut); }
  /* body copy sits clearly below the title */
  .reveal p,.reveal li{ font-size:0.72em; line-height:1.5; }
  .reveal strong{ font-weight:600; }
  .reveal em{ color:var(--mut); }
  .reveal a{ color:inherit; text-decoration:underline; text-decoration-thickness:1px; text-underline-offset:2px; }
  .reveal ul,.reveal ol{ margin-left:0.2em; }
  .reveal li{ margin:0.12em 0; }
  .reveal li::marker{ color:var(--faint); }
  /* code */
  .reveal pre{ width:100%; box-shadow:none; font-size:0.46em; line-height:1.5; margin:0.6em 0; }
  .reveal pre code{ display:block; font-family:'IBM Plex Mono',monospace; background:#f7f7f5; color:var(--ink2);
    border:1px solid var(--line); border-radius:6px; padding:1em 1.2em; max-height:none;
    line-height:1.6 !important; white-space:pre; overflow-x:auto; overflow-y:visible; }
  .reveal code:not(pre code){ font-family:'IBM Plex Mono',monospace; font-size:0.82em; background:#f2f2ef;
    padding:0.05em 0.34em; border-radius:4px; }
  /* blockquote — editorial, thin rule */
  .reveal blockquote{ width:100%; box-shadow:none; background:none; border-left:2px solid var(--ink);
    padding:0.1em 0 0.1em 1em; margin:0.7em 0; font-style:italic; color:var(--mut); font-size:0.72em; }
  .reveal blockquote strong{ color:var(--ink2); }
  /* tables */
  .reveal table{ font-size:0.64em; border-collapse:collapse; margin-top:0.4em; }
  .reveal table th{ font-weight:500; font-style:italic; color:var(--mut); text-align:left;
    border-bottom:1.5px solid var(--ink); padding:0.3em 0.7em; }
  .reveal table td{ border-bottom:1px solid var(--line); padding:0.35em 0.7em; }
  /* title / closing slides centered */
  .reveal .slides>section:first-of-type,.reveal .slides>section:last-of-type{ text-align:center; }
  .reveal .slides>section:first-of-type h1{ margin-bottom:0.15em; }
  .reveal .slides>section:first-of-type strong{ display:inline-block; margin-top:1.4em; font-weight:500;
    letter-spacing:0.02em; }
  .reveal .slides>section:last-of-type p{ color:var(--mut); font-size:0.7em; }
  /* pagination */
  .reveal .slide-number{ background:none; color:var(--faint); font-family:'Lora',serif; font-style:italic; }
  /* ---------- diagrams ---------- */
  .diag{ font-family:'Lora',Georgia,serif; margin:0.3em 0; }
  .diag .row{ display:flex; align-items:center; justify-content:center; gap:8px; flex-wrap:wrap; margin:8px 0; }
  .diag .col{ display:flex; flex-direction:column; gap:10px; }
  .diag .side .bi{ display:flex; align-items:center; gap:8px; }
  .diag .node{ border:1px solid var(--ink); border-radius:5px; background:#fff; padding:9px 13px;
    text-align:center; line-height:1.25; min-width:92px; }
  .diag .node.soft{ border-color:#c4c4c4; }
  .diag .node.hub{ border-width:2px; }
  .diag .node b{ display:block; font-weight:500; font-size:0.5em; letter-spacing:0.01em; }
  .diag .node small{ display:block; font-style:italic; color:var(--mut2); font-size:0.4em; margin-top:3px; line-height:1.35; }
  .diag .arr{ color:#a0a0a0; font-size:0.62em; padding:0 2px; }
  .diag .band{ position:relative; border:1px solid var(--line); border-radius:9px; padding:22px 16px 14px; margin:8px 0; }
  .diag .band-label{ position:absolute; top:-0.62em; left:16px; background:#fff; padding:0 8px;
    font-style:italic; color:var(--mut); font-size:0.42em; letter-spacing:0.02em; }
  .diag .loads{ text-align:center; color:var(--mut); font-style:italic; font-size:0.44em; margin:2px 0; }
  .diag .loads .down{ display:block; font-style:normal; font-size:1.5em; color:#a0a0a0; line-height:1; }
  /* ---------- rollout screenshots ---------- */
  .shots{ display:flex; gap:16px; justify-content:center; align-items:flex-start; margin:0.6em 0 0.2em; }
  .shots figure{ margin:0; flex:1 1 0; min-width:0; text-align:center; }
  .shots img{ width:100%; height:auto; max-height:340px; object-fit:contain; background:#fff;
    border:1px solid var(--line); border-radius:6px; }
  .shots figcaption{ margin-top:7px; font-style:italic; color:var(--mut); font-size:0.46em; letter-spacing:0.02em; }
  .reveal .inspector-link{ text-align:center; color:var(--mut); font-size:0.62em; margin-top:0.5em; }
  .reveal .inspector-link a{ color:var(--ink); }
</style>
</head>
<body>
<div class="reveal"><div class="slides">
  <section data-markdown data-separator="^\r?\n---\r?\n$">
    <textarea data-template>
__MD__
    </textarea>
  </section>
</div></div>
<script src="https://cdn.jsdelivr.net/npm/reveal.js@5.1.0/dist/reveal.js"></script>
<script src="https://cdn.jsdelivr.net/npm/reveal.js@5.1.0/plugin/markdown/markdown.js"></script>
<script>
  const deck = new Reveal({ hash:true, slideNumber:'c/t', width:1280, height:760, margin:0.055,
    controlsTutorial:false, plugins:[ RevealMarkdown ] });
  deck.initialize();
</script>
</body>
</html>
"""
html = html.replace("__MD__", md)
pathlib.Path("docs/presentations/saas-world.html").write_text(html)
print("wrote docs/presentations/saas-world.html", len(html), "bytes")
