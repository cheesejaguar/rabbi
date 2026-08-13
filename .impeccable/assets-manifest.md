# Production image assets

Generated with the native OpenAI image-generation tool on 2026-08-12. Raw generated PNGs are preserved under `frontend/assets/images/originals/`; production derivatives use lossless PNG.

## `braid-macro.png`

- Production file: `frontend/assets/images/braid-macro.png`
- Production dimensions: 1800 x 1200 px
- Preserved original: `frontend/assets/images/originals/braid-macro-generated.png`
- Original dimensions: 1536 x 1024 px
- Post-processing: proportional resize to 1800 x 1200 with `sips`; no crop or distortion.
- Exact prompt:

```text
Use case: stylized-concept
Asset type: wide editorial website image
Primary request: An original extreme macro material study of exactly four distinct braided strands woven together, evoking the Braided Light visual identity without forming a literal logo.
Scene/background: abstract seamless field with shallow depth of field; no environment or props.
Subject: four broad satin-textile ribbons, two deep indigo/navy, one cool cobalt blue, and one luminous silver-white, visibly crossing over and under in a sophisticated four-strand weave.
Style/medium: premium photorealistic macro product photography, tactile woven fibers and fine satin grain, restrained high-end editorial art direction.
Composition/framing: horizontal 3:2 landscape, 1800x1200 or larger, braid sweeps diagonally across the frame with generous calm negative space near the outer edges; crop feels intentional and usable as a web feature image.
Lighting/mood: cool raking side light, quiet sculptural shadows, subtle specular highlights, crisp but not harsh.
Color palette: #F3F6FA, #FAFCFE, #122033, #52647C, #C6D2E1, #315DA8, #214784 only.
Quality: high.
Constraints: exactly four interwoven material strands; original composition; no text; no letters; no logo; no people; no religious symbols; no Star of David; no Hebrew; no watermark.
Avoid: gold, purple AI gradients, parchment, mystical glow, particles, lens flare, excessive bloom, plastic surfaces, stock-photo staging, clutter, fake writing, symbols pretending to be text.
```

Runtime derivative: `frontend/assets/images/braid-macro.jpg`, 1800 x 1200, JPEG quality 84, used by the landing page to reduce transfer size while the prompted PNG remains the production master.

Modern runtime derivative: `frontend/assets/images/braid-macro.avif`, 1800 x 1200, AVIF quality 68, preferred by supporting browsers with the JPEG retained as fallback.

## `source-sheets.png`

- Production file: `frontend/assets/images/source-sheets.png`
- Production dimensions: 1800 x 1200 px
- Preserved original: `frontend/assets/images/originals/source-sheets-generated.png`
- Original dimensions: 1536 x 1024 px
- Post-processing: proportional resize to 1800 x 1200 with `sips`; no crop or distortion.
- Exact prompt:

```text
Use case: stylized-concept
Asset type: wide editorial website image
Primary request: An original still-life abstraction of layered translucent source sheets and reference cards, expressing careful research and source-grounded reasoning through material and light alone.
Scene/background: clean cool mineral-white studio surface fading to pale blue-gray, no room context and no props beyond the sheets.
Subject: several thin translucent frosted-glass and vellum-like rectangular sheets, offset in an elegant shallow stack, with softly rounded corners, subtle cobalt edge lighting, delicate cast shadows, and varied transparency; every sheet surface is completely blank.
Style/medium: premium photorealistic product still life with architectural restraint, refined materials, crisp edges, gentle atmospheric depth.
Composition/framing: horizontal 3:2 landscape, 1800x1200 or larger; layered sheets occupy the right two-thirds and recede diagonally, with quiet negative space on the left; suitable as a web feature image.
Lighting/mood: soft cool daylight plus restrained blue edge light, luminous but calm, no glow effects.
Color palette: #F3F6FA, #FAFCFE, #122033, #52647C, #C6D2E1, #315DA8, #214784 only.
Materials/textures: frosted translucent glass, thin clear polymer, soft vellum, matte mineral surface.
Quality: high.
Constraints: all card and sheet faces must be entirely blank; no text; no letters; no numbers; no lines or glyphs that could be mistaken for writing; no icons; no logos; no people; no religious symbols; no Star of David; no Hebrew; no watermark.
Avoid: fake or legible text, placeholder lines, symbols pretending to be text, document UI, book icons, quotation marks, interface chrome, gold, purple AI gradients, parchment, mystical effects, particles, lens flare, excessive bloom, clutter.
```

Runtime derivative: `frontend/assets/images/source-sheets.jpg`, 1800 x 1200, JPEG quality 86, used by the landing page to reduce transfer size while the prompted PNG remains the production master.

Modern runtime derivative: `frontend/assets/images/source-sheets.avif`, 1800 x 1200, AVIF quality 68, preferred by supporting browsers with the JPEG retained as fallback.

## `social-card.png`

- Production file: `frontend/assets/images/social-card.png`
- Production dimensions: 1200 x 630 px
- Preserved original: `frontend/assets/images/originals/social-card-generated.png`
- Original dimensions: 1733 x 908 px, RGBA
- Post-processing: proportional scale-to-fill and centered 2 px horizontal crop to 1200 x 630 with `ffmpeg`; transparent edge pixels flattened over `#F3F6FA`. Text and identity artwork were not altered.
- Exact prompt:

```text
Use case: logo-brand
Asset type: 1200x630 social sharing card
Primary request: A minimal, premium social card for rebbe.dev using the Braided Light identity.
Scene/background: clean luminous mineral-white to pale blue-gray field with a very subtle cool vignette, no scene or props.
Subject: on the left, one abstract lowercase-r brand mark constructed from exactly four broad interwoven ribbon strands in deep navy, cobalt blue, slate blue, and silver-white; sculptural but simple, recognizably a lowercase r, no religious symbolism. On the right, the exact wordmark and headline.
Style/medium: polished editorial brand design, restrained modern typography, generous whitespace, crisp high-end web product aesthetic.
Composition/framing: exact final aspect ratio 1200x630 (1.9048:1); keep every important element well inside a centered 1200x630-safe composition with generous outer margins. Mark occupies the left quarter. Text is left-aligned in the right two-thirds with clear hierarchy.
Lighting/mood: cool soft studio illumination, calm, intelligent, trustworthy.
Color palette: background #F3F6FA and #FAFCFE; text #122033; secondary #52647C; mark #122033 #52647C #C6D2E1 #315DA8 #214784.
Text (verbatim): "rebbe.dev"
Text (verbatim): "Thoughtful Jewish guidance, grounded in sources."
Typography: exact lowercase wordmark “rebbe.dev” in a clean dark navy geometric sans serif; exact headline “Thoughtful Jewish guidance, grounded in sources.” in a refined dark navy sans serif, line-broken naturally, with no other words anywhere.
Quality: high.
Constraints: render both text strings exactly, letter for letter and punctuation for punctuation; exactly four interwoven strands in the lowercase-r mark; original composition; no additional text; no Hebrew; no fake text; no icons; no people; no Star of David; no watermark.
Avoid: gold, purple AI gradients, parchment, mystical glow, particles, lens flare, excessive bloom, religious motifs, decorative symbols, pseudo-writing, faux UI, clutter.
```
