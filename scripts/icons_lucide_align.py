#!/usr/bin/env python3
"""图标体系统一：全部 SVG 内联图标替换为 Lucide 0.555.0 官方 path（与参考项目同体系）。
权威来源：参考项目 node_modules/lucide-react@0.555.0（只读提取）。
规范：viewBox 0 0 24 24 · fill none · stroke currentColor · 圆角端点；
     nav-ico 描边 2.1（参考 :464），其余描边 2（lucide 默认）。
用法：python3 scripts/icons_lucide_align.py（写回前打印替换统计）"""
import re, sys, pathlib

ROOT = pathlib.Path("/Users/w/Desktop/Model-Gateway/model_gateway/web/static")

# Lucide 0.555.0 官方 path（node_modules 只读提取，attr 顺序保持官方）
L = {
  "check": '<path d="M20 6 9 17l-5-5"/>',
  "chevron-right": '<path d="m9 18 6-6-6-6"/>',
  "cpu": '<path d="M12 20v2"/><path d="M12 2v2"/><path d="M17 20v2"/><path d="M17 2v2"/><path d="M2 12h2"/><path d="M2 17h2"/><path d="M2 7h2"/><path d="M20 12h2"/><path d="M20 17h2"/><path d="M20 7h2"/><path d="M7 20v2"/><path d="M7 2v2"/><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="8" y="8" width="8" height="8" rx="1"/>',
  "download": '<path d="M12 15V3"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/>',
  "eye": '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/>',
  "file-text": '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/><path d="M14 2v5a1 1 0 0 0 1 1h5"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
  "log-in": '<path d="m10 17 5-5-5-5"/><path d="M15 12H3"/><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/>',
  "pencil": '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>',
  "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
  "refresh-cw": '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
  "search": '<path d="m21 21-4.34-4.34"/><circle cx="11" cy="11" r="8"/>',
  "server": '<rect width="20" height="8" x="2" y="2" rx="2" ry="2"/><rect width="20" height="8" x="2" y="14" rx="2" ry="2"/><line x1="6" x2="6.01" y1="6" y2="6"/><line x1="6" x2="6.01" y1="18" y2="18"/>',
  "settings": '<path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915"/><circle cx="12" cy="12" r="3"/>',
  "shield": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
  "trash-2": '<path d="M10 11v6"/><path d="M14 11v6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
  "user": '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  "wrench": '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.106-3.105c.32-.322.863-.22.983.218a6 6 0 0 1-8.259 7.057l-7.91 7.91a1 1 0 0 1-2.999-3l7.91-7.91a6 6 0 0 1 7.057-8.259c.438.12.54.662.219.984z"/>',
  "layout-grid": '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
  "database": '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5V19A9 3 0 0 0 21 19V5"/><path d="M3 12A9 3 0 0 0 21 12"/>',
  "layers": '<path d="M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z"/><path d="M2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12"/><path d="M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17"/>',
  "chart-column": '<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
  "list": '<path d="M3 5h.01"/><path d="M3 12h.01"/><path d="M3 19h.01"/><path d="M8 5h13"/><path d="M8 12h13"/><path d="M8 19h13"/>',
  "key": '<path d="m15.5 7.5 2.3 2.3a1 1 0 0 0 1.4 0l2.1-2.1a1 1 0 0 0 0-1.4L19 4"/><path d="m21 2-9.6 9.6"/><circle cx="7.5" cy="15.5" r="5.5"/>',
  "sliders-vertical": '<path d="M10 8h4"/><path d="M12 21v-9"/><path d="M12 8V3"/><path d="M17 16h4"/><path d="M19 12V3"/><path d="M19 21v-5"/><path d="M3 14h4"/><path d="M5 10V3"/><path d="M5 21v-7"/>',
  "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
  "moon": '<path d="M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268c.344-.215.825-.004.803.401"/>',
  "monitor": '<rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/><line x1="12" x2="12" y1="17" y2="21"/>',
  "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  "menu": '<path d="M4 5h16"/><path d="M4 12h16"/><path d="M4 19h16"/>',
  "activity": '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>',
  "arrow-left-right": '<path d="M8 3 4 7l4 4"/><path d="M4 7h16"/><path d="m16 21 4-4-4-4"/><path d="M20 17H4"/>',
}

# 旧图标指纹（旧 Feather/早期 Lucide path 的唯一子串）→ 目标图标名
FP = [
  ('rx="1.5"', "layout-grid"),
  ('rx="8" ry="3"', "database"),
  ('polygon points="12 2 2 7', "layers"),
  ('<line x1="12" y1="20" x2="12" y2="10"/>', "chart-column"),
  ('<line x1="8" y1="6" x2="21" y2="6"/>', "list"),
  ('M21 2l-2 2m-7.61', "key"),
  ('<line x1="4" y1="21" x2="4" y2="14"/>', "sliders-vertical"),
  ('<line x1="3" y1="6" x2="21" y2="6"/>', "menu"),
  ('points="9 18 15 12 9 6"', "chevron-right"),
  ('l1.4-1.4', "sun"),
  ('M21 12.8A9', "moon"),
  ('width="20" height="14"', "monitor"),
  ('points="3 6 5 6 21 6"', "trash-2"),
  ('width="20" height="8"', "server"),
  ('<rect x="9" y="9" width="6" height="6"/>', "cpu"),
  ('points="7 10 12 15 17 10"', "download"),
  ('-4-4H8', "user"),
  ('M12 22s8-4', "shield"),
  ('16.65', "search"),
  ('points="23 4 23 10', "refresh-cw"),
  ('M3.51 9a9', "refresh-cw"),
  ('M19.4 15a1.65', "settings"),
  ('3.77-3.77', "wrench"),
  ('M14 2H6', "file-text"),
  ('<line x1="12" y1="5"', "plus"),
  ('points="20 6 9 17 4 12"', "check"),
  ('M1 12s4', "eye"),
  ('points="22 12 18 12', "activity"),
  ('d="m16 3 4 4-4 4"', "arrow-left-right"),
  ('M17 3a2.85', "pencil"),
  ('d="M18 6 6 18"', "x"),
]

FILES = [
  ROOT / "index.html",
  ROOT / "js/pages/dashboard.js",
  ROOT / "js/pages/stats.js",
  ROOT / "templates/template-providers.html",
  ROOT / "templates/template-skills.html",
]

SVG_RE = re.compile(r"<svg\b[^>]*>.*?</svg>", re.S)
BRAND = "M4 17V7l8 10 8-10v10"  # 品牌 M 字 logo（品牌标识，非体系图标，保留）

def identify(inner):
    for fp, name in FP:
        if fp in inner:
            return name
    return None

def fix_sw(open_tag, name):
    """描边规范化：nav-ico → 2.1（参考 :464），品牌 logo 不动，其余 → 2。"""
    if BRAND in open_tag or (name is None):
        return open_tag
    target = "2.1" if "nav-ico" in open_tag else "2"
    tag = re.sub(r'stroke-width="[0-9.]+"', f'stroke-width="{target}"', open_tag)
    if 'stroke-linejoin' not in tag:  # 统一圆角连接（lucide 默认）
        tag = tag.replace('stroke-linecap="round"',
                          'stroke-linecap="round" stroke-linejoin="round"')
    return tag

total = {}
for path in FILES:
    src = path.read_text()
    def repl(m):
        block = m.group(0)
        open_tag = block[:block.index(">") + 1]
        inner = block[len(open_tag):-6]
        name = identify(inner)
        if name is None or BRAND in inner:
            return block  # 品牌 logo / 未指纹（已是新版 lucide）保留
        total[name] = total.get(name, 0) + 1
        return fix_sw(open_tag, name) + L[name] + "</svg>"
    out = SVG_RE.sub(repl, src)
    if out != src:
        path.write_text(out)
        print(f"{path.name}: 已写回")
print("替换统计（图标 × 次数）:", dict(sorted(total.items(), key=lambda kv: -kv[1])))
