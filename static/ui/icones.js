/* BestEditor — emoji → ícone do Font Awesome (v84_161).
   O ui.js troca os emojis do site por estes ícones. "r:" = estilo regular (contorno), "b:" = marcas; o resto é solid.
   Emoji sem ícone aqui some da tela (fica guardado escondido, pra copiar/colar continuar igual). */
window.UI_ICONES = {
  // estados
  "⚠": "triangle-exclamation", "✅": "circle-check", "✔": "check", "✓": "check", "☑": "square-check", "❌": "circle-xmark",
  "✖": "xmark", "✕": "xmark", "⛔": "ban", "🚫": "ban", "❓": "circle-question", "❔": "circle-question", "💡": "lightbulb",
  "⏳": "hourglass-half", "⏱": "stopwatch", "⏰": "clock", "🕒": "clock", "🕐": "clock", "🕰": "clock", "🕘": "clock-rotate-left",
  "🔔": "bell", "🔒": "lock", "🔑": "key", "🛡": "shield-halved", "🔥": "fire", "⭐": "star", "★": "star", "💯": "award", "🏆": "trophy",
  "🎉": "champagne-glasses", "✨": "wand-magic-sparkles", "💫": "star", "💥": "burst", "⚡": "bolt", "🌀": "spinner", "♻": "recycle",
  "🔴": "circle", "🟡": "circle", "⚫": "circle", "⚪": "r:circle", "⭕": "r:circle", "🟣": "circle", "🔷": "diamond", "💎": "gem",
  "●": "circle", "⬛": "square", "⬜": "r:square", "🔲": "r:square", "🔳": "square",
  // ações
  "➕": "plus", "🗑": "trash-can", "💾": "floppy-disk", "📋": "clipboard", "📎": "paperclip", "📌": "thumbtack", "📍": "location-dot",
  "✏": "pen", "✎": "pen", "✍": "pen-nib", "🖍": "highlighter", "📝": "file-pen", "🔁": "rotate", "🔄": "arrows-rotate", "↻": "rotate-right",
  "↺": "rotate-left", "↩": "rotate-left", "↶": "arrow-rotate-left", "↷": "arrow-rotate-right", "🔀": "shuffle", "⤵": "turn-down",
  "⬇": "download", "⬆": "upload", "📥": "inbox", "📤": "share-from-square", "⏬": "angles-down", "🔼": "caret-up", "🔽": "caret-down",
  "➡": "arrow-right", "⬅": "arrow-left", "➤": "play", "►": "play", "▶": "play", "◀": "backward-step", "⏸": "pause", "⏹": "stop",
  "⏺": "circle-dot", "⏭": "forward-step", "⏪": "backward", "⏩": "forward", "⇥": "arrow-right-to-bracket", "⇤": "arrow-left-long",
  "🔍": "magnifying-glass", "🔎": "magnifying-glass", "🔗": "link", "🧲": "magnet", "🧹": "broom", "🧽": "eraser", "🧼": "soap",
  "🧪": "flask", "🔬": "microscope", "🩺": "stethoscope", "🩹": "bandage", "🔧": "wrench", "🛠": "screwdriver-wrench", "⚙": "gear",
  "🔌": "plug", "🔦": "lightbulb", "🧩": "puzzle-piece", "🎛": "sliders", "🎚": "sliders", "📏": "ruler", "📐": "ruler-combined",
  "👁": "eye", "👀": "eye", "🙈": "eye-slash", "🔇": "volume-xmark", "🔊": "volume-high", "📢": "bullhorn", "📣": "bullhorn",
  "✋": "hand", "👉": "hand-point-right", "👍": "thumbs-up", "🤐": "comment-slash", "💬": "comments", "💭": "comment-dots",
  "🗣": "comment", "🤔": "circle-question", "🧠": "brain", "🧭": "compass", "🎯": "bullseye", "🚀": "rocket", "🏁": "flag-checkered",
  "🪄": "wand-magic-sparkles", "✂": "scissors", "🔢": "list-ol", "🔤": "font", "🔠": "font", "🏷": "tag", "🎁": "gift",
  // mídia
  "🎬": "clapperboard", "🎞": "film", "🎥": "video", "📹": "video", "📷": "camera", "📸": "camera-retro", "🖼": "image", "🎨": "palette",
  "🎙": "microphone", "🎧": "headphones", "🎵": "music", "♪": "music", "🎶": "music", "📺": "tv", "🖥": "desktop", "💻": "laptop",
  "📱": "mobile-screen", "📲": "mobile-screen-button", "⌨": "keyboard", "🪧": "sign-hanging", "🃏": "id-card", "🪪": "id-card",
  "🌫": "smog", "🌗": "circle-half-stroke", "☀": "sun", "🌅": "sun", "🌇": "city", "🌊": "water", "💧": "droplet", "💦": "droplet",
  "🌋": "volcano", "🌪": "tornado", "🍃": "leaf", "🧊": "cube", "🌐": "globe", "🗺": "map", "🕸": "spider", "🕳": "circle",
  // arquivos e textos
  "📄": "file-lines", "📑": "copy", "📜": "scroll", "📚": "book", "📖": "book-open", "📘": "book", "📰": "newspaper", "🗞": "newspaper",
  "📁": "folder", "📂": "folder-open", "🗂": "folder-tree", "📦": "box", "🧾": "receipt", "📊": "chart-column", "📉": "chart-line",
  "📈": "chart-line", "📅": "calendar", "📆": "calendar-days", "🗓": "calendar-days", "🔖": "bookmark",
  // pessoas e temas
  "🤖": "robot", "👤": "user", "👥": "users", "🧑": "user", "👧": "child", "🧔": "user", "👴": "person-cane", "🎭": "masks-theater",
  "🕵": "user-secret", "👽": "user-astronaut", "🎓": "graduation-cap", "💼": "briefcase", "🏢": "building", "🏭": "industry",
  "🛒": "cart-shopping", "💰": "sack-dollar", "💸": "money-bill-wave", "💳": "credit-card", "🆓": "tag", "🎣": "fish", "🐟": "fish",
  "🐢": "gauge", "🐍": "b:python", "🦋": "feather", "🍪": "cookie-bite", "🎌": "flag", "⚖": "scale-balanced", "⚓": "anchor",
  "🚗": "car", "🛫": "plane-departure", "💨": "wind", "🔮": "eye", "⛏": "person-digging", "💚": "heart", "💔": "heart-crack",
  "🙅": "user-slash", "🤝": "handshake", "〰": "wave-square", "➿": "infinity",
};
