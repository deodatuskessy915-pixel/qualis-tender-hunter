#!/usr/bin/env python3
"""
build_dashboard.py — Qualis Tender Hunter (Sessions 3 + 4)

Reads two data sources and produces ONE self-contained HTML dashboard:

  1. qualis_live_tenders.json — output of nest_scraper.py (Session 4).
     Currently-open NeST tenders, with real buyer + real deadline.
     SHOWN AT THE TOP of the dashboard.

  2. qualis_matches.json — output of fetch.py (Session 2).
     9,020 OCDS planning-stage matches. Buyer/deadline are not in OCDS
     for planning-stage records.
     SHOWN IN A COLLAPSIBLE 'PIPELINE' SECTION at the bottom.

Run:  python build_dashboard.py

Inputs and output are absolute paths so it works regardless of cwd.
"""
import json
import os
import sys
from datetime import datetime, timezone

# --- Paths ---------------------------------------------------------------
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))

# Windows absolute paths (developer's laptop)
WIN_LIVE    = r"G:\My Drive\personal\BILLIONAIRE\Master of Projects\project-setup\tender-hunter\qualis_live_tenders.json"
WIN_OCDS    = r"D:\tacker project\qualis-hunter-session2\qualis-hunter-pkg\qualis_matches.json"
WIN_OUTPUT  = r"G:\My Drive\personal\BILLIONAIRE\Master of Projects\project-setup\tender-hunter\qualis_dashboard.html"

# CI / GitHub Actions fallback: files sit next to this script in the repo root
CI_LIVE     = os.path.join(SCRIPT_DIR, "qualis_live_tenders.json")
CI_OCDS     = os.path.join(SCRIPT_DIR, "qualis_matches.json")
CI_OUTPUT   = os.path.join(SCRIPT_DIR, "qualis_dashboard.html")


def resolve_paths():
    live = WIN_LIVE   if os.path.exists(WIN_LIVE)   else CI_LIVE
    ocds = WIN_OCDS   if os.path.exists(WIN_OCDS)   else CI_OCDS
    out  = WIN_OUTPUT if os.path.isdir(os.path.dirname(WIN_OUTPUT)) else CI_OUTPUT
    return live, ocds, out


# --- Trim records to keep inlined payload small --------------------------
def trim_live(m):
    """Compact a live-tender record for the dashboard.
    Supports both v2 (long field names) and v3 (short field names) scraper output.
    """
    # v3 short names take priority; v2 long names are fallbacks
    return {
        "id":       m.get("entity_uuid") or m.get("id"),
        "t":        m.get("t") or m.get("title") or "",
        "buyer":    m.get("buyer") or "",
        "ref":      m.get("ref") or m.get("reference_number") or "",
        "type":     m.get("type") or m.get("entity_type") or "",   # TENDER / FRAMEWORK
        "cat":      m.get("cat") or m.get("category") or "",
        "subcat":   m.get("subcat") or m.get("sub_category") or "",
        "fy":       m.get("fy") or m.get("financial_year") or "",
        "inv":      m.get("inv") or m.get("invitation_date") or "",
        "dl":       m.get("dl") or m.get("deadline") or "",        # "YYYY-MM-DDTHH:MM"
        "dl_days":  m.get("dl_days"),
        "lots":     m.get("lots") or m.get("lot_count") or 1,
        "addendum": bool(m.get("addendum") or m.get("has_addendum")),
        "local_only": bool(m.get("local_only")),
        "s":        m.get("s") or m.get("score") or 0,
        "r":        m.get("r") or m.get("reason") or "",
        "k":        m.get("k") or m.get("matched_keywords") or [],
        "u":        m.get("u") or m.get("nest_url") or "",
        "p":        bool(m.get("p") or m.get("priority")),         # priority buyer?
        "pm":       m.get("pm") or m.get("priority_match") or "",  # which pattern matched
        "value_est":  m.get("value_est") or "",
        "value_tier": m.get("value_tier") or "STANDARD",
        "value_basis": m.get("value_basis") or "",
    }


def trim_ocds(m):
    """Compact an OCDS planning-stage match record (Session 3 shape)."""
    return {
        "id": m.get("tender_id") or m.get("ocid"),
        "t":  m.get("title") or "",
        "s":  m.get("score") or 0,
        "r":  m.get("reason") or "",
        "k":  m.get("matched_keywords") or [],
        "rg": m.get("region") or None,
        "u":  m.get("nest_url") or "",
    }


def main():
    live_path, ocds_path, out_path = resolve_paths()
    print(f"Reading live:     {live_path}")
    print(f"Reading OCDS:     {ocds_path}")

    with open(live_path, "r", encoding="utf-8") as f:
        live = json.load(f)
    if os.path.exists(ocds_path):
        with open(ocds_path, "r", encoding="utf-8") as f:
            ocds = json.load(f)
    else:
        print(f"  (qualis_matches.json not found at {ocds_path} — pipeline section will be empty)")
        ocds = {"matches": [], "year": "—", "total": 0, "still_relevant": 0, "match_count": 0, "generated_at": None}

    live_matches = [trim_live(m) for m in live.get("matches", [])]
    # Priority buyers come first (0 vs 1), then by score desc, then deadline asc.
    live_matches.sort(key=lambda x: (0 if x["p"] else 1, -x["s"], x["dl"] or "9999"))
    priority_count = sum(1 for m in live_matches if m["p"])

    ocds_matches = [trim_ocds(m) for m in ocds.get("matches", [])]
    ocds_matches.sort(key=lambda x: -x["s"])

    # Build OCDS keyword frequency table for the multi-select filter
    kw_freq = {}
    for m in ocds_matches:
        for k in m["k"]:
            kw_freq[k] = kw_freq.get(k, 0) + 1
    kw_sorted = sorted(kw_freq.items(), key=lambda x: -x[1])

    meta = {
        "built_at":          datetime.now(timezone.utc).isoformat(),
        # Live (NeST)
        "live_source":       live.get("source"),
        "live_generated_at": live.get("generated_at"),
        "live_total_pub":    live.get("total_published"),
        "live_fetched":      live.get("fetched"),
        "live_match_count":  live.get("match_count"),
        "live_priority":     priority_count,
        # OCDS
        "ocds_year":         ocds.get("year"),
        "ocds_total":        ocds.get("total"),
        "ocds_relevant":     ocds.get("still_relevant"),
        "ocds_match_count":  ocds.get("match_count"),
        "ocds_generated_at": ocds.get("generated_at"),
        # OCDS filter helpers
        "kw_top":            kw_sorted[:50],
    }

    data_json = json.dumps({
        "live": live_matches,
        "ocds": ocds_matches,
        "meta": meta,
    }, ensure_ascii=False, separators=(",", ":"))

    doc = TEMPLATE.replace("__DATA__", data_json)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"Wrote: {out_path}")
    print(f"  Live matches:     {len(live_matches)}")
    print(f"  OCDS pipeline:    {len(ocds_matches)}")
    print(f"  File size:        {os.path.getsize(out_path) / 1024 / 1024:.2f} MB")


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Qualis Tender Hunter</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
/* ===== ROOT ===== */
:root {
  --bg:       #0b0e17;
  --bg2:      #10131f;
  --surf:     #161926;
  --surf2:    #1c2035;
  --surf3:    #232840;
  --border:   rgba(255,255,255,0.07);
  --border2:  rgba(255,255,255,0.13);
  --y:        #FFB800;
  --y2:       #ffd060;
  --y-dim:    rgba(255,184,0,0.12);
  --text:     #e8eaf2;
  --text2:    #8a93ad;
  --text3:    #4d566e;
  --green:    #22c55e;
  --green-d:  rgba(34,197,94,0.12);
  --amber:    #f59e0b;
  --amber-d:  rgba(245,158,11,0.12);
  --red:      #ef4444;
  --red-d:    rgba(239,68,68,0.12);
  --blue:     #818cf8;
  --blue-d:   rgba(129,140,248,0.12);
  --r:        10px;
  --rs:       6px;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{font-family:'Inter',-apple-system,system-ui,sans-serif;background:var(--bg);color:var(--text);-webkit-font-smoothing:antialiased;line-height:1.5;min-height:100vh}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--surf3);border-radius:3px}
a{color:inherit;text-decoration:none}

/* ===== HEADER ===== */
.hdr{
  position:sticky;top:0;z-index:200;
  background:rgba(11,14,23,0.92);
  backdrop-filter:blur(16px);
  -webkit-backdrop-filter:blur(16px);
  border-bottom:1px solid var(--border);
}
.hdr-inner{
  max-width:1440px;margin:0 auto;
  padding:0 28px;
  display:flex;align-items:center;gap:24px;
  height:60px;
}
.brand{display:flex;align-items:center;gap:11px;flex-shrink:0}
.brand-q{
  width:34px;height:34px;
  background:var(--y);border-radius:8px;
  display:flex;align-items:center;justify-content:center;
  font-weight:800;font-size:17px;color:#000;letter-spacing:-0.02em;
  box-shadow:0 0 20px rgba(255,184,0,0.35);
}
.brand-words h1{font-size:15px;font-weight:700;letter-spacing:-0.01em;line-height:1.15}
.brand-words h1 em{font-style:normal;color:var(--y)}
.brand-words small{font-size:10.5px;color:var(--text3);letter-spacing:0.02em;font-weight:400}

.hdr-stats{display:flex;gap:10px;flex:1;justify-content:center;flex-wrap:wrap}
.hpill{
  display:inline-flex;align-items:center;gap:7px;
  background:var(--surf);border:1px solid var(--border);
  border-radius:999px;padding:5px 13px;font-size:12.5px;white-space:nowrap;
}
.hpill .pn{font-weight:700;font-size:14px}
.hpill .pl{color:var(--text2)}
.hpill.hl{border-color:rgba(239,68,68,0.25)}.hpill.hl .pn{color:var(--red)}
.hpill.hm{border-color:rgba(255,184,0,0.25)}.hpill.hm .pn{color:var(--y)}
.hpill.hp{border-color:rgba(34,197,94,0.25)}.hpill.hp .pn{color:var(--green)}
.hpill.ho .pn{color:var(--blue)}

.hdr-date{font-size:11px;color:var(--text3);flex-shrink:0;white-space:nowrap}

@media(max-width:768px){
  .hdr-inner{padding:0 16px;gap:12px;height:auto;flex-wrap:wrap;padding-top:10px;padding-bottom:10px}
  .hdr-stats{justify-content:flex-start}
  .hdr-date{display:none}
}

/* ===== LAYOUT ===== */
.wrap{max-width:1440px;margin:0 auto;padding:28px 28px 80px}
@media(max-width:768px){.wrap{padding:18px 14px 60px}}

/* ===== SECTION HEADER ===== */
.sec-hd{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:18px;gap:12px;flex-wrap:wrap}
.sec-hd-left h2{font-size:19px;font-weight:700;letter-spacing:-0.02em;display:flex;align-items:center;gap:10px}
.sec-hd-left .sub{font-size:12.5px;color:var(--text2);margin-top:4px}

.pulse-dot{
  width:9px;height:9px;border-radius:50%;background:var(--red);flex-shrink:0;position:relative;
}
.pulse-dot::after{
  content:'';position:absolute;inset:-4px;border-radius:50%;
  background:var(--red);opacity:0.35;
  animation:ripple 2s ease-out infinite;
}
@keyframes ripple{0%{transform:scale(1);opacity:0.4}70%{transform:scale(2.2);opacity:0}100%{transform:scale(2.2);opacity:0}}

.sec-select{
  background:var(--surf);border:1px solid var(--border2);
  color:var(--text);padding:8px 12px;border-radius:var(--rs);
  font-family:inherit;font-size:12.5px;cursor:pointer;outline:none;
}
.sec-select:focus{border-color:var(--y)}

/* ===== LIVE GRID ===== */
.live-sec{margin-bottom:36px}
.live-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(370px,1fr));gap:14px}
@media(max-width:460px){.live-grid{grid-template-columns:1fr}}

/* ===== TENDER CARD ===== */
.tc{
  background:var(--surf);border:1px solid var(--border);
  border-radius:var(--r);overflow:hidden;
  transition:border-color .2s,box-shadow .2s,transform .2s;
  display:flex;flex-direction:column;
}
.tc:hover{border-color:var(--border2);box-shadow:0 8px 36px rgba(0,0,0,.35);transform:translateY(-2px)}
.tc.pri{
  border-color:rgba(255,184,0,.3);
  background:linear-gradient(140deg,rgba(255,184,0,.05) 0%,var(--surf) 45%);
  box-shadow:0 0 0 1px rgba(255,184,0,.08),inset 0 0 50px rgba(255,184,0,.02);
}
.tc.pri:hover{border-color:rgba(255,184,0,.55);box-shadow:0 8px 36px rgba(0,0,0,.35),0 0 30px rgba(255,184,0,.08)}

/* top urgency stripe */
.tc-stripe{height:3px;width:100%;flex-shrink:0}
.tc-stripe.urg{background:linear-gradient(90deg,#ef4444,#f97316)}
.tc-stripe.soo{background:linear-gradient(90deg,#f59e0b,#fbbf24)}
.tc-stripe.saf{background:linear-gradient(90deg,#22c55e,#4ade80)}

.tc-body{padding:16px;flex:1;display:flex;flex-direction:column;gap:10px}

/* top row: badges + ring */
.tc-row1{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
.tc-badges{display:flex;align-items:center;gap:5px;flex-wrap:wrap}

.bdg{
  display:inline-flex;align-items:center;gap:3px;
  padding:3px 8px;border-radius:4px;
  font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
}
.bdg-pri{background:var(--y);color:#000}
.bdg-ten{background:var(--blue-d);color:var(--blue);border:1px solid rgba(129,140,248,.2)}
.bdg-fra{background:var(--amber-d);color:#fbbf24;border:1px solid rgba(245,158,11,.2)}
.bdg-add{background:var(--amber-d);color:#fbbf24;border:1px solid rgba(245,158,11,.15);font-size:10px}

/* score ring */
.sring-wrap{display:flex;flex-direction:column;align-items:center;gap:2px;flex-shrink:0}
.sring{position:relative;width:50px;height:50px}
.sring svg{transform:rotate(-90deg)}
.sring .rb{fill:none;stroke:var(--surf3);stroke-width:4}
.sring .rf{fill:none;stroke-width:4;stroke-linecap:round}
.sring-num{
  position:absolute;inset:0;
  display:flex;align-items:center;justify-content:center;
  font-size:14px;font-weight:800;letter-spacing:-0.02em;
}
.sring-lbl{font-size:9.5px;color:var(--text3);font-weight:600;text-transform:uppercase;letter-spacing:.05em}
.rf.c{stroke:#f59e0b}.sring-num.c{color:#f59e0b}
.rf.s{stroke:#22c55e}.sring-num.s{color:#22c55e}
.rf.o{stroke:#4b5563}.sring-num.o{color:var(--text2)}

/* title */
.tc-title{font-size:14px;font-weight:600;color:var(--text);line-height:1.4}

/* buyer */
.tc-buyer{display:flex;align-items:center;gap:7px;font-size:12.5px;color:var(--text2)}
.tc-buyer .bname{color:var(--text);font-weight:500}
.tc-buyer .pmatch{color:var(--y);font-size:10.5px;font-weight:600;margin-left:2px}

/* value estimate badge */
.tc-val{
  display:inline-flex;align-items:center;gap:5px;
  padding:4px 10px;border-radius:5px;font-size:11.5px;font-weight:600;
  align-self:flex-start;
}
.tc-val-high{background:rgba(34,197,94,0.12);color:#4ade80;border:1px solid rgba(34,197,94,.18)}
.tc-val-medium{background:rgba(245,158,11,0.12);color:#fbbf24;border:1px solid rgba(245,158,11,.18)}
.tc-val-standard{background:var(--surf3);color:var(--text2);border:1px solid var(--border)}

/* meta 2-col grid */
.tc-meta{
  display:grid;grid-template-columns:1fr 1fr;gap:6px 14px;
  padding:10px;background:var(--surf2);border-radius:7px;font-size:11.5px;
}
.tc-meta-it strong{display:block;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;color:var(--text3);margin-bottom:1px}
.tc-meta-it span{color:var(--text2)}

/* countdown chip */
.tc-cd{
  display:inline-flex;align-items:center;gap:6px;
  padding:5px 10px;border-radius:5px;font-size:11.5px;font-weight:600;
  align-self:flex-start;
}
.tc-cd.urg{background:var(--red-d);color:#f87171;border:1px solid rgba(239,68,68,.18)}
.tc-cd.soo{background:var(--amber-d);color:#fbbf24;border:1px solid rgba(245,158,11,.18)}
.tc-cd.saf{background:var(--green-d);color:#4ade80;border:1px solid rgba(34,197,94,.18)}

/* keywords */
.tc-kws{display:flex;flex-wrap:wrap;gap:4px}
.kp{background:var(--surf3);color:var(--text2);border-radius:4px;padding:2px 7px;font-size:11px;font-weight:500}

/* reason */
.tc-rsn{font-size:11.5px;color:var(--text3);font-style:italic;margin-top:auto}

/* card footer */
.tc-foot{
  display:flex;align-items:center;justify-content:space-between;
  padding:10px 16px;
  background:var(--surf2);border-top:1px solid var(--border);
}
.tc-ref{font-size:10.5px;color:var(--text3);font-family:'Courier New',monospace;letter-spacing:.01em}
.btn-nest{
  display:inline-flex;align-items:center;gap:5px;
  background:var(--y);color:#000;
  padding:8px 16px;border-radius:6px;
  font-size:12.5px;font-weight:700;
  transition:background .15s,transform .1s,box-shadow .15s;
  box-shadow:0 2px 8px rgba(255,184,0,.25);
}
.btn-nest:hover{background:var(--y2);transform:scale(1.02);box-shadow:0 4px 16px rgba(255,184,0,.35)}

/* empty state */
.live-empty{
  text-align:center;padding:60px 20px;
  background:var(--surf);border:1px dashed var(--border2);border-radius:var(--r);
  color:var(--text3);
}
.live-empty .ei{font-size:38px;margin-bottom:14px}
.live-empty h3{font-size:15px;font-weight:600;color:var(--text2);margin-bottom:6px}

/* ===== PIPELINE SECTION ===== */
.pipe-sec{
  background:var(--surf);border:1px solid var(--border);
  border-radius:var(--r);overflow:hidden;
}
.pipe-tog{
  display:flex;align-items:center;justify-content:space-between;
  padding:16px 22px;cursor:pointer;user-select:none;
  transition:background .15s;
}
.pipe-tog:hover{background:var(--surf2)}
.pipe-tog-l{display:flex;align-items:center;gap:11px}
.pipe-tog-l h2{font-size:16px;font-weight:700}
.pipe-cnt-bdg{
  background:var(--surf3);border:1px solid var(--border);
  color:var(--text2);border-radius:999px;
  padding:2px 10px;font-size:12px;font-weight:600;
}
.pipe-chev{
  width:20px;height:20px;color:var(--text3);
  transition:transform .25s;
}
.pipe-chev.open{transform:rotate(180deg)}

.pipe-body{display:none}
.pipe-body.open{display:block}

/* banner */
.pipe-banner{
  background:rgba(245,158,11,.07);
  border-bottom:1px solid rgba(245,158,11,.18);
  padding:9px 22px;font-size:12px;color:#fbbf24;
  display:flex;align-items:center;gap:7px;
}

/* controls */
.pipe-ctrls{
  display:grid;grid-template-columns:2fr 1fr 1fr 1.2fr;gap:14px;
  padding:14px 22px;background:var(--surf2);border-bottom:1px solid var(--border);
}
@media(max-width:900px){.pipe-ctrls{grid-template-columns:1fr 1fr}}
@media(max-width:500px){.pipe-ctrls{grid-template-columns:1fr}}
.pc-lbl{font-size:10.5px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--text3);margin-bottom:6px}
.pc-inp{
  width:100%;background:var(--surf);border:1px solid var(--border2);
  color:var(--text);padding:7px 11px;border-radius:var(--rs);
  font-family:inherit;font-size:13px;outline:none;
  transition:border-color .15s;
}
.pc-inp:focus{border-color:var(--y)}
.pc-inp::placeholder{color:var(--text3)}
.str-btns{
  display:flex;background:var(--surf);border:1px solid var(--border2);
  border-radius:var(--rs);overflow:hidden;
}
.str-btns button{
  flex:1;padding:7px 0;background:none;border:none;
  color:var(--text2);font-family:inherit;font-size:12px;font-weight:500;cursor:pointer;
  transition:background .15s,color .15s;
}
.str-btns button.on{background:var(--y);color:#000;font-weight:700}
.sc-range{display:flex;align-items:center;gap:6px}
.sc-range input{width:58px;text-align:center}
.kw-tags-row{margin-top:6px;display:flex;flex-wrap:wrap;gap:4px}
.kw-tag{
  display:inline-flex;align-items:center;gap:3px;
  background:var(--y);color:#000;
  border-radius:4px;padding:2px 8px;
  font-size:11px;font-weight:700;cursor:pointer;
}
.kw-tag::after{content:'×';font-size:13px}

/* summary bar */
.pipe-sum{
  display:flex;align-items:center;justify-content:space-between;
  padding:9px 22px;background:var(--bg2);border-bottom:1px solid var(--border);
  font-size:12.5px;color:var(--text2);flex-wrap:wrap;gap:8px;
}
.pipe-sum strong{color:var(--text)}
.pgr{display:flex;gap:5px;align-items:center}
.pgr-btn{
  background:var(--surf);border:1px solid var(--border2);color:var(--text2);
  padding:5px 12px;border-radius:var(--rs);cursor:pointer;
  font-family:inherit;font-size:12px;
  transition:border-color .15s,color .15s;
}
.pgr-btn:hover:not(:disabled){border-color:var(--y);color:var(--y)}
.pgr-btn:disabled{opacity:.35;cursor:not-allowed}
.pgr-info{font-size:12px;color:var(--text3)}

/* table */
.pipe-tbl-wrap{overflow-x:auto}
table.pt{width:100%;border-collapse:collapse;font-size:12.5px}
table.pt thead th{
  background:var(--bg2);color:var(--text3);
  font-size:10.5px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;
  padding:9px 14px;text-align:left;border-bottom:1px solid var(--border);
  white-space:nowrap;user-select:none;cursor:default;
}
table.pt thead th.srt{cursor:pointer}
table.pt thead th.srt:hover{color:var(--y)}
table.pt thead th .sa{color:var(--y);margin-left:3px}
table.pt tbody tr{border-bottom:1px solid var(--border);transition:background .1s}
table.pt tbody tr:hover{background:var(--surf2)}
table.pt tbody tr:last-child{border-bottom:none}
table.pt td{padding:10px 14px;vertical-align:top;color:var(--text2)}
td.sc-td{text-align:center;width:72px}
.sc-bdg{display:inline-block;padding:4px 10px;border-radius:6px;font-weight:700;font-size:14px}
.sc-bdg.c{background:rgba(245,158,11,.14);color:#fbbf24}
.sc-bdg.s{background:rgba(34,197,94,.14);color:#4ade80}
.sc-bdg.o{background:var(--surf3);color:var(--text3)}
td.ttl-td .ttl{color:var(--text);font-weight:500;line-height:1.35}
td.ttl-td .rsn{font-size:11px;color:var(--text3);font-style:italic;margin-top:2px}
td.tbd-td{font-size:11.5px;color:var(--text3);font-style:italic}
td.tbd-td .tbd-note{color:var(--y);font-size:10px;font-style:normal;font-weight:600;display:block;margin-top:1px}
td.kw-td .kp{display:inline-block;background:var(--surf3);color:var(--text2);border-radius:3px;padding:1px 5px;font-size:10.5px;margin:1px 2px 1px 0}
td.kw-td .kp.on{background:var(--y);color:#000;font-weight:700}
td.act-td{text-align:right;white-space:nowrap}
.btn-view{
  display:inline-flex;align-items:center;gap:4px;
  background:var(--surf3);color:var(--text2);
  padding:5px 11px;border-radius:var(--rs);font-size:11.5px;font-weight:500;
  transition:background .15s,color .15s;
}
.btn-view:hover{background:var(--y);color:#000}
.pipe-empty{text-align:center;padding:50px 20px;color:var(--text3)}

/* ===== FOOTER ===== */
.qfoot{
  text-align:center;padding:22px;font-size:11.5px;
  color:var(--text3);border-top:1px solid var(--border);
  background:var(--bg2);margin-top:36px;
}
.qfoot span{color:var(--text2)}
</style>
</head>
<body>

<!-- ═══ HEADER ═══ -->
<header class="hdr">
  <div class="hdr-inner">
    <div class="brand">
      <div class="brand-q">Q</div>
      <div class="brand-words">
        <h1>Qualis <em>Tender Hunter</em></h1>
        <small>Tanzania Infrastructure Intelligence</small>
      </div>
    </div>
    <div class="hdr-stats" id="hdr-stats"></div>
    <div class="hdr-date" id="hdr-date"></div>
  </div>
</header>

<!-- ═══ MAIN ═══ -->
<div class="wrap">

  <!-- LIVE BIDDABLE NOW -->
  <section class="live-sec">
    <div class="sec-hd">
      <div class="sec-hd-left">
        <h2><span class="pulse-dot"></span>Biddable Now</h2>
        <div class="sub" id="live-sub">Loading…</div>
      </div>
      <div>
        <select class="sec-select" id="live-sort">
          <option value="default">Priority → Score → Deadline</option>
          <option value="deadline">Deadline — most urgent</option>
          <option value="score">Score — highest first</option>
        </select>
      </div>
    </div>

    <div class="live-grid" id="live-grid"></div>
    <div class="live-empty" id="live-empty" style="display:none">
      <div class="ei">🔍</div>
      <h3>No matches right now</h3>
      <p>No Qualis-profile tenders in the current NeST set. Re-run nest_scraper.py to refresh.</p>
    </div>
  </section>

  <!-- PIPELINE -->
  <section class="pipe-sec">
    <div class="pipe-tog" id="pipe-tog" role="button" aria-expanded="false">
      <div class="pipe-tog-l">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--text3);flex-shrink:0"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
        <h2>Pipeline — OCDS Planning Records</h2>
        <span class="pipe-cnt-bdg" id="pipe-cnt-bdg">…</span>
      </div>
      <svg class="pipe-chev" id="pipe-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
    </div>

    <div class="pipe-body" id="pipe-body">
      <div class="pipe-banner">
        ⚠&nbsp; Planning-stage data: Buyer, deadline &amp; value appear once procurement advances to tender stage — which then surfaces in <strong>Biddable Now</strong> above.
      </div>

      <div class="pipe-ctrls">
        <div>
          <div class="pc-lbl">Search title / reason</div>
          <input class="pc-inp" type="text" id="pipe-search" placeholder="transformer, grid, solar…">
        </div>
        <div>
          <div class="pc-lbl">Strength</div>
          <div class="str-btns" id="str-btns">
            <button data-v="all" class="on">All</button>
            <button data-v="strong">Strong</button>
            <button data-v="soft">Soft</button>
          </div>
        </div>
        <div>
          <div class="pc-lbl">Score range</div>
          <div class="sc-range">
            <input class="pc-inp" type="number" id="sc-min" value="0" min="0" max="999">
            <span style="color:var(--text3)">–</span>
            <input class="pc-inp" type="number" id="sc-max" value="999" min="0" max="999">
          </div>
        </div>
        <div>
          <div class="pc-lbl">Keyword filter</div>
          <select class="pc-inp" id="kw-sel">
            <option value="">— add keyword filter —</option>
          </select>
          <div class="kw-tags-row" id="kw-tags"></div>
        </div>
      </div>

      <div class="pipe-sum">
        <div id="pipe-res-txt">…</div>
        <div class="pgr">
          <button class="pgr-btn" id="prev-pg">‹ Prev</button>
          <span class="pgr-info" id="pg-info">…</span>
          <button class="pgr-btn" id="next-pg">Next ›</button>
        </div>
      </div>

      <div class="pipe-tbl-wrap">
        <table class="pt" id="pipe-tbl">
          <thead>
            <tr>
              <th class="srt" data-col="s" style="width:74px">Score <span class="sa" id="arr-s">▼</span></th>
              <th style="min-width:270px">Title</th>
              <th style="width:110px">Buyer</th>
              <th style="width:110px">Deadline</th>
              <th style="width:88px">Value</th>
              <th style="width:210px">Keywords</th>
              <th style="width:100px"></th>
            </tr>
          </thead>
          <tbody id="pipe-tbody"></tbody>
        </table>
        <div class="pipe-empty" id="pipe-empty" style="display:none">
          <div style="font-size:30px;margin-bottom:10px">🔎</div>
          <div style="color:var(--text2);font-weight:500">No records match the current filters</div>
        </div>
      </div>
    </div>
  </section>

</div><!-- /wrap -->

<footer class="qfoot">
  <span>Qualis Engineering Limited</span>&nbsp;·&nbsp;CRB Class V Electrical Contractor&nbsp;·&nbsp;TIN 157-968-718&nbsp;·&nbsp;Dar es Salaam, Tanzania
</footer>

<script>
const D = __DATA__;
const LIVE = D.live, OCDS = D.ocds, META = D.meta;

/* helpers */
function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
function sc(s){return s>=20?"c":s>=10?"s":"o"}
function isStr(r){return /^Strong/i.test(r.r||"")}
function daysTo(dl){if(!dl)return null;const t=new Date(dl).getTime();if(isNaN(t))return null;return(t-Date.now())/86400000}
function uc(d){if(d==null)return"soo";if(d<2)return"urg";if(d<7)return"soo";return"saf"}
function ul(d){
  if(d==null)return"Deadline TBD";
  if(d<0)return"Closed";
  if(d<0.05)return"Closes today!";
  const n=Math.ceil(d);
  return n===1?"1 day left":`${n} days left`;
}
function fdt(dl){
  if(!dl)return"—";
  const dt=new Date(dl);if(isNaN(dt))return dl;
  return dt.toLocaleString(undefined,{day:"2-digit",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit"});
}

/* score ring */
function ring(score){
  const R=18,circ=2*Math.PI*R;
  const pct=Math.min(score/60,1);
  const off=(circ*(1-pct)).toFixed(2);
  const cls=sc(score);
  const col=cls==="c"?"#f59e0b":cls==="s"?"#22c55e":"#4b5563";
  return `<div class="sring-wrap">
    <div class="sring">
      <svg width="50" height="50" viewBox="0 0 50 50">
        <circle class="rb" cx="25" cy="25" r="${R}"/>
        <circle class="rf ${cls}" cx="25" cy="25" r="${R}"
          stroke-dasharray="${circ.toFixed(2)}"
          stroke-dashoffset="${off}"
          stroke="${col}"/>
      </svg>
      <div class="sring-num ${cls}">${score}</div>
    </div>
    <div class="sring-lbl">score</div>
  </div>`;
}

/* ── HEADER ── */
function renderHdr(){
  const p=META.live_priority||0;
  const hv=(META.live_high_value||0);
  document.getElementById("hdr-stats").innerHTML=`
    <div class="hpill hl"><span class="pn">${(META.live_total_pub||0).toLocaleString()}</span><span class="pl">open on NeST</span></div>
    <div class="hpill hm"><span class="pn">${(META.live_match_count||0).toLocaleString()}</span><span class="pl">live matches</span></div>
    ${p>0?`<div class="hpill hp"><span class="pn">${p}</span><span class="pl">priority buyer${p>1?"s":""}</span></div>`:""}
    ${hv>0?`<div class="hpill" style="border-color:rgba(34,197,94,.25)"><span class="pn" style="color:var(--green)">${hv}</span><span class="pl">high value</span></div>`:""}
    <div class="hpill ho"><span class="pn">${OCDS.length.toLocaleString()}</span><span class="pl">in pipeline</span></div>`;
  const d=META.live_generated_at?META.live_generated_at.slice(0,10):"—";
  document.getElementById("hdr-date").textContent=`Updated ${d}`;
}

/* ── LIVE ── */
function sortedLive(){
  const by=document.getElementById("live-sort").value;
  const a=LIVE.slice();
  if(by==="deadline") a.sort((x,y)=>(x.dl||"9999").localeCompare(y.dl||"9999"));
  else if(by==="score") a.sort((x,y)=>y.s-x.s);
  else a.sort((x,y)=>x.p===y.p?(y.s-x.s||(x.dl||"9999").localeCompare(y.dl||"9999")):(x.p?-1:1));
  return a;
}

function renderLive(){
  const grid=document.getElementById("live-grid");
  const empty=document.getElementById("live-empty");
  const sub=document.getElementById("live-sub");
  const data=sortedLive();
  const p=META.live_priority||0;
  const pn=p>0?` · <strong style="color:var(--y)">${p} priority buyer${p>1?"s":""}</strong>`:"";
  sub.innerHTML=data.length===0
    ?`No Qualis matches in the ${(META.live_total_pub||0).toLocaleString()} currently open NeST tenders.`
    :`<strong>${data.length}</strong> Qualis-matching tenders from <strong>${(META.live_total_pub||0).toLocaleString()}</strong> open on NeST${pn}`;
  if(!data.length){grid.innerHTML="";empty.style.display="block";return}
  empty.style.display="none";

  grid.innerHTML=data.map(r=>{
    const d=daysTo(r.dl),uclass=uc(d),ulabel=ul(d);
    const pb=r.p?`<span class="bdg bdg-pri">★ Priority</span>`:"";
    const tb=r.type==="FRAMEWORK"?`<span class="bdg bdg-fra">Framework</span>`:`<span class="bdg bdg-ten">Tender</span>`;
    const ab=r.addendum?`<span class="bdg bdg-add">Addendum</span>`:"";
    const pm=r.p&&r.pm?`<span class="pmatch">· matched "${esc(r.pm)}"</span>`:"";
    const kws=(r.k||[]).slice(0,5).map(k=>`<span class="kp">${esc(k)}</span>`).join("");
    const icon=uclass==="urg"?"🔴":uclass==="soo"?"🟡":"🟢";
    return `<div class="tc${r.p?" pri":""}">
      <div class="tc-stripe ${uclass}"></div>
      <div class="tc-body">
        <div class="tc-row1">
          <div class="tc-badges">${pb}${tb}${ab}</div>
          ${ring(r.s)}
        </div>
        <div class="tc-title">${esc(r.t)}</div>
        <div class="tc-buyer">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;color:var(--text3)"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
          <span class="bname">${esc(r.buyer)}</span>${pm}
        </div>
        ${r.value_est?`<div class="tc-val tc-val-${(r.value_tier||"STANDARD").toLowerCase()}">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
          <span>${esc(r.value_est)}</span>
        </div>`:""}
        <div class="tc-meta">
          <div class="tc-meta-it"><strong>Category</strong><span>${esc(r.cat||"—")}</span></div>
          <div class="tc-meta-it"><strong>Sub-category</strong><span>${esc(r.subcat||"—")}</span></div>
          <div class="tc-meta-it"><strong>Deadline</strong><span>${fdt(r.dl)}</span></div>
          <div class="tc-meta-it"><strong>Lots</strong><span>${r.lots||1}</span></div>
        </div>
        <div class="tc-cd ${uclass}">${icon} ${ulabel}</div>
        <div class="tc-kws">${kws}</div>
        <div class="tc-rsn">${esc(r.r)}</div>
      </div>
      <div class="tc-foot">
        <span class="tc-ref">${esc(r.ref)}</span>
        <a class="btn-nest" href="${esc(r.u)}" target="_blank" rel="noopener">
          View on NeST
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M7 7h10v10"/><path d="M7 17 17 7"/></svg>
        </a>
      </div>
    </div>`;
  }).join("");
}

/* ── PIPELINE ── */
const PS={q:"",str:"all",mn:0,mx:999,kws:[],col:"s",dir:"desc",page:1,ps:50};

function initPipeKws(){
  const sel=document.getElementById("kw-sel");
  for(const [k,n] of (META.kw_top||[])){
    const o=document.createElement("option");o.value=k;o.textContent=`${k} (${n})`;sel.appendChild(o);
  }
  document.getElementById("pipe-cnt-bdg").textContent=`${OCDS.length.toLocaleString()} records`;
}

function filterPipe(){
  const q=PS.q.trim().toLowerCase();
  const ks=new Set(PS.kws);
  return OCDS.filter(r=>{
    if(r.s<PS.mn||r.s>PS.mx)return false;
    if(PS.str==="strong"&&!isStr(r))return false;
    if(PS.str==="soft"&&isStr(r))return false;
    if(q&&!(r.t+" "+r.r).toLowerCase().includes(q))return false;
    if(ks.size&&!PS.kws.every(k=>(r.k||[]).includes(k)))return false;
    return true;
  }).sort((a,b)=>{
    const d=PS.dir==="asc"?1:-1;
    return a[PS.col]===b[PS.col]?0:(a[PS.col]>b[PS.col]?1:-1)*d;
  });
}

function renderPipe(){
  document.getElementById("kw-tags").innerHTML=PS.kws.map(k=>`<span class="kw-tag" data-k="${esc(k)}">${esc(k)}</span>`).join("");
  const arr=document.getElementById("arr-s");
  arr.textContent=PS.dir==="asc"?"▲":"▼";
  arr.style.opacity=PS.col==="s"?"1":"0";

  const filt=filterPipe(),total=filt.length;
  const pages=Math.max(1,Math.ceil(total/PS.ps));
  if(PS.page>pages)PS.page=pages;
  const st=(PS.page-1)*PS.ps,en=Math.min(st+PS.ps,total);
  const slice=filt.slice(st,en);

  const tb=document.getElementById("pipe-tbody");
  const tbl=document.getElementById("pipe-tbl");
  const emp=document.getElementById("pipe-empty");

  if(!total){tb.innerHTML="";tbl.style.display="none";emp.style.display="block"}
  else{tbl.style.display="";emp.style.display="none"}

  document.getElementById("pipe-res-txt").innerHTML=total===0
    ?`<strong>0</strong> records`
    :`Showing <strong>${(st+1).toLocaleString()}–${en.toLocaleString()}</strong> of <strong>${total.toLocaleString()}</strong>${total!==OCDS.length?` (filtered from ${OCDS.length.toLocaleString()})` :""}`;
  document.getElementById("pg-info").textContent=`${PS.page} / ${pages}`;
  document.getElementById("prev-pg").disabled=PS.page<=1;
  document.getElementById("next-pg").disabled=PS.page>=pages;

  if(!total)return;
  const ks=new Set(PS.kws);
  tb.innerHTML=slice.map(r=>{
    const cls=sc(r.s);
    const kw=(r.k||[]).map(k=>`<span class="kp${ks.has(k)?" on":""}">${esc(k)}</span>`).join("");
    return `<tr>
      <td class="sc-td"><span class="sc-bdg ${cls}">${r.s}</span></td>
      <td class="ttl-td"><div class="ttl">${esc(r.t)}</div><div class="rsn">${esc(r.r)}${r.rg?` · <b>${esc(r.rg)}</b>`:""}</div></td>
      <td class="tbd-td">TBD<span class="tbd-note">→ tender stage</span></td>
      <td class="tbd-td">TBD<span class="tbd-note">→ tender stage</span></td>
      <td class="tbd-td">TBD<span class="tbd-note">→ tender stage</span></td>
      <td class="kw-td">${kw}</td>
      <td class="act-td"><a class="btn-view" href="${esc(r.u)}" target="_blank" rel="noopener">View <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M7 7h10v10"/><path d="M7 17 17 7"/></svg></a></td>
    </tr>`;
  }).join("");
}

/* ── INIT ── */
function init(){
  renderHdr();
  renderLive();
  initPipeKws();
  renderPipe();

  document.getElementById("live-sort").addEventListener("change",renderLive);

  document.getElementById("pipe-tog").addEventListener("click",()=>{
    const b=document.getElementById("pipe-body");
    const c=document.getElementById("pipe-chev");
    const open=b.classList.toggle("open");
    c.classList.toggle("open",open);
  });

  document.getElementById("pipe-search").addEventListener("input",e=>{PS.q=e.target.value;PS.page=1;renderPipe()});
  document.querySelectorAll("#str-btns button").forEach(b=>{
    b.addEventListener("click",()=>{
      document.querySelectorAll("#str-btns button").forEach(x=>x.classList.remove("on"));
      b.classList.add("on");PS.str=b.dataset.v;PS.page=1;renderPipe();
    });
  });
  document.getElementById("sc-min").addEventListener("input",e=>{PS.mn=+e.target.value||0;PS.page=1;renderPipe()});
  document.getElementById("sc-max").addEventListener("input",e=>{PS.mx=+e.target.value||999;PS.page=1;renderPipe()});
  document.getElementById("kw-sel").addEventListener("change",e=>{
    const v=e.target.value;if(v&&!PS.kws.includes(v)){PS.kws.push(v);PS.page=1;renderPipe()}e.target.value="";
  });
  document.getElementById("kw-tags").addEventListener("click",e=>{
    const t=e.target.closest(".kw-tag");if(!t)return;
    PS.kws=PS.kws.filter(k=>k!==t.dataset.k);PS.page=1;renderPipe();
  });
  document.querySelectorAll("#pipe-tbl th.srt").forEach(th=>{
    th.addEventListener("click",()=>{
      const c=th.dataset.col;
      if(PS.col===c)PS.dir=PS.dir==="asc"?"desc":"asc";else{PS.col=c;PS.dir="desc";}
      renderPipe();
    });
  });
  document.getElementById("prev-pg").addEventListener("click",()=>{if(PS.page>1){PS.page--;renderPipe()}});
  document.getElementById("next-pg").addEventListener("click",()=>{PS.page++;renderPipe()});
}
document.addEventListener("DOMContentLoaded",init);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
