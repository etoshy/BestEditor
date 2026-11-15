"""
🎨 v84_397 — estilos de arte prontos para as imagens geradas (cenas do canal e thumbnails).

Cada estilo: "nome" (na tela), "en" (a estética, em inglês, que vai no prompt), "neg" (o que evitar),
"real" (como redesenhar uma pessoa/objeto real de foto nesse estilo) e "thumb" (o reforço pra thumbnail).
Só descrevem a ESTÉTICA (traço, cor, textura) — nunca copiam a obra de um artista.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

_NEG_FOTO = "photorealistic, photograph, photo, 3D render, CGI, glossy, airbrushed"

ESTILOS: Dict[str, Dict[str, str]] = {
    "rusty": {
        "nome": "🖌 Rusty Art (desenho à mão, rabiscado e sujo)",
        "en": ("Hand-drawn digital sketch illustration in a rough, painterly 'rusty art' style: loose scratchy ink linework with "
               "visible sketch strokes and uneven line weight, dry textured brush strokes, a muted desaturated palette of olive "
               "green, sepia and rust brown, ash gray, charcoal and dirty off-white, grimy rust-colored washes with drips, smudges "
               "and paint splatter, pale faces with heavy tired shadows under the eyes, messy hair strands falling over the face, "
               "moody melancholic atmosphere, simple flat background or plain gray/off-white paper, slightly unfinished hand-made "
               "sketchbook look, like an indie artist's drawing"),
        "neg": _NEG_FOTO + ", clean vector art, smooth gradients, polished cel-shaded anime, bright saturated colors, neon",
        "real": ("redrawn in the same rough hand-drawn rusty sketch style (loose ink lines, muted olive/sepia/gray washes), "
                 "keeping every recognizable feature"),
        "thumb": "bold readable silhouette, the face or main subject large and close, strong dark-light contrast against a plain flat background",
    },
    "esboco_lapis": {
        "nome": "✏️ Esboço a lápis (grafite, preto e branco)",
        "en": ("Graphite pencil sketch on off-white paper: expressive hand-drawn lines, cross-hatching and smudged shading, "
               "visible construction lines and eraser marks, black-and-white only, soft paper grain, artist's sketchbook study"),
        "neg": _NEG_FOTO + ", color, painted, digital painting, clean vector",
        "real": "redrawn as a detailed graphite pencil portrait sketch, keeping every recognizable feature",
        "thumb": "the subject large and centered, dark heavy shading on one side for contrast, empty paper around it",
    },
    "nanquim": {
        "nome": "🖋 Nanquim / tinta aguada",
        "en": ("Black ink wash illustration: bold brush-and-ink strokes with varied line weight, gray watery ink washes, ink "
               "splatter and dry-brush texture, lots of white paper, dramatic minimal composition, monochrome with deep blacks"),
        "neg": _NEG_FOTO + ", color, bright colors, clean vector, gradient",
        "real": "redrawn in expressive black ink brush strokes and gray washes, keeping every recognizable feature",
        "thumb": "a strong black ink silhouette against white paper, maximum contrast",
    },
    "oleo_classico": {
        "nome": "🖼 Pintura a óleo clássica (museu)",
        "en": ("Classical oil painting in the style of old master museum paintings: rich textured brush strokes, dramatic "
               "chiaroscuro lighting from one side, warm earthy palette of ochre, umber and deep shadows, varnished canvas texture, "
               "timeless solemn mood"),
        "neg": _NEG_FOTO + ", cartoon, anime, flat colors, vector, neon",
        "real": "repainted as a classical oil portrait with chiaroscuro, keeping every recognizable feature",
        "thumb": "one face or figure lit dramatically against a very dark background",
    },
    "gravura": {
        "nome": "📜 Gravura antiga (xilogravura / bico de pena)",
        "en": ("Antique engraving illustration: fine parallel hatching and cross-hatching lines, woodcut/etching texture, "
               "aged cream paper, black ink with optional single sepia tone, 18th-19th century book illustration look"),
        "neg": _NEG_FOTO + ", modern digital painting, bright colors, anime, smooth shading",
        "real": "redrawn as an antique engraving with fine hatching, keeping every recognizable feature",
        "thumb": "the subject large with heavy black hatching for contrast on aged paper",
    },
    "aquarela": {
        "nome": "💧 Aquarela suja (manchada, solta)",
        "en": ("Loose expressive watercolor illustration: bleeding color washes, blooms and drips, visible pencil underdrawing, "
               "rough cold-press paper texture, muted earthy palette with one accent color, imperfect hand-painted edges"),
        "neg": _NEG_FOTO + ", clean vector, hard cel shading, neon",
        "real": "repainted in loose watercolor washes over a pencil sketch, keeping every recognizable feature",
        "thumb": "a dark saturated focal area on the subject, the rest fading into white paper",
    },
    "cartoon_grosso": {
        "nome": "🖍 Cartoon de traço grosso (feito à mão)",
        "en": ("Hand-drawn 2D cartoon: thick wobbly black outlines, simple exaggerated shapes and expressive faces, flat colors "
               "with a little rough crayon/marker texture, limited palette, playful but slightly gritty indie cartoon look"),
        "neg": _NEG_FOTO + ", realistic proportions, detailed rendering, glossy anime",
        "real": "redrawn as a simple thick-outlined cartoon caricature, keeping the recognizable features",
        "thumb": "a big exaggerated facial expression filling the frame, bold outline, plain flat color background",
    },
    "noir_quadrinho": {
        "nome": "🦇 Quadrinho noir (P&B + uma cor)",
        "en": ("Noir comic book art: heavy black shadows and spotted blacks, stark high-contrast black and white with a single "
               "accent color (deep red), gritty ink texture, dramatic angles, halftone dots"),
        "neg": _NEG_FOTO + ", many colors, pastel, soft lighting, cute",
        "real": "redrawn as a high-contrast noir comic panel, keeping every recognizable feature",
        "thumb": "a face half in deep shadow, extreme contrast, one red accent",
    },
    "anime_sombrio": {
        "nome": "🌑 Anime sombrio pintado",
        "en": ("Dark painterly anime illustration: semi-realistic anime faces, soft painted shading with visible brush texture, "
               "desaturated cold palette with deep shadows, cinematic moody lighting, melancholic atmosphere"),
        "neg": _NEG_FOTO + ", chibi, bright cheerful colors, flat cel shading, cute",
        "real": "redrawn as a semi-realistic dark anime character, keeping every recognizable feature",
        "thumb": "a close-up face with intense eyes, rim light against a dark background",
    },
    "colagem": {
        "nome": "✂️ Colagem de papel (recortes)",
        "en": ("Mixed-media paper collage: cut-out vintage paper pieces with torn edges, halftone print textures, old book pages "
               "and tape, layered shapes with drop shadows, muted retro palette, handmade analog look"),
        "neg": "3D render, CGI, glossy, smooth digital painting, anime",
        "real": "cut out from an old printed photograph and pasted into the collage, keeping every recognizable feature",
        "thumb": "one big cut-out subject on a plain textured paper background",
    },
    "foto_cinema": {
        "nome": "📷 Foto cinematográfica (realista)",
        "en": ("Cinematic photograph: realistic, shallow depth of field, dramatic directional light, rich but natural color "
               "grading, film grain, documentary feel"),
        "neg": "cartoon, illustration, drawing, anime, painting, 3D render",
        "real": "as a realistic photograph, keeping every recognizable feature",
        "thumb": "one clear focal subject close to the camera, strong emotion, dramatic high-contrast light",
    },
}


def opcoes() -> List[Tuple[str, str]]:
    return [(k, v["nome"]) for k, v in ESTILOS.items()]


def estilo_thumb(chave: str) -> str:
    """O estilo completo de UMA thumbnail (formato do ESTILO_PADRAO: com {lado})."""
    e = ESTILOS.get(chave)
    if not e:
        return ""
    return ("YouTube thumbnail, 16:9, one strong focal subject, strong emotion, clear contrast, large empty negative space on "
            "the {lado} third for a big title added later. Art style: " + e["en"] + ". " + e["thumb"]
            + ". No text, no letters, no words, no watermark, no logo. Avoid: " + e["neg"] + ".")
