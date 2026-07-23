#!/usr/bin/env python3
"""
patch_template.py — Applies all layout fixes to template.html
Run once after any template.html update: python patch_template.py
"""
import sys, re
from pathlib import Path

TARGET = Path(__file__).parent / 'template.html'
if not TARGET.exists():
    sys.exit(f"ERROR: {TARGET} not found")

content = TARGET.read_text(encoding='utf-8')
original = content
patches = []

def p(name, old, new):
    patches.append((name, old, new))

p("chart-card overflow:hidden",
""".chart-card {
  background: var(--bg1);
  border: 1px solid var(--border);
  border-radius: var(--r);
  padding: 14px 16px;
  display: flex; flex-direction: column;
}""",
""".chart-card {
  background: var(--bg1);
  border: 1px solid var(--border);
  border-radius: var(--r);
  padding: 14px 16px;
  display: flex; flex-direction: column;
  overflow: hidden;
  min-width: 0;
}""")

p("chart-wrap overflow:hidden",
'.chart-wrap { position: relative; flex: 1; min-height: 160px; }',
'.chart-wrap { position: relative; flex: 1; min-height: 0; overflow: hidden; }')

p("switchTab issues destroy+rebuild",
"""    // After layout settles, force all chart canvases to redraw at correct size.
    // Charts built while the panel was hidden have stale canvas dimensions;
    // calling update() after the panel is visible triggers _draw() with correct wrap size.
    setTimeout(() => {
      window._chartAgg = window._wLastAgg || null;
      if (Object.keys(chartInstances).length > 0) {
        // Charts already exist — just force a resize+redraw on each
        Object.values(chartInstances).forEach(c => { try { c.update(); } catch(e){} });
      } else {
        // No charts yet (first visit) — full build
        const _cg = document.getElementById('chart-grid');
        if (_cg) _cg.removeAttribute('data-built');
        renderCharts();
      }
      window._chartAgg = null;
    }, 60);""",
"""    // Always destroy+rebuild — charts built while tab was hidden have canvas width=0.
    // c.update() cannot fix a 0-width canvas. Only destroy+rebuild works.
    setTimeout(() => {
      Object.values(chartInstances).forEach(c => { try { c.destroy(); } catch(e){} });
      Object.keys(chartInstances).forEach(k => delete chartInstances[k]);
      const _cg = document.getElementById('chart-grid');
      if (_cg) _cg.removeAttribute('data-built');
      window._chartAgg = window._wLastAgg || null;
      renderCharts();
      window._chartAgg = null;
    }, 60);""")

p("switchTab costs destroy+resize",
"  if (id === 'costs')    requestAnimationFrame(() => _renderCosts());",
"""  if (id === 'costs')    requestAnimationFrame(() => {
    ['costs-scurve-chart','costs-disc-chart','costs-wbs-chart'].forEach(function(cid) {
      const cv = document.getElementById(cid);
      if (cv && cv._chart) { try { cv._chart.destroy(); } catch(e){} cv._chart = null; }
    });
    _renderCosts();
    setTimeout(() => {
      ['costs-scurve-chart','costs-disc-chart','costs-wbs-chart'].forEach(function(cid) {
        const cv = document.getElementById(cid);
        if (cv && cv._chart) cv._chart.resize();
      });
    }, 50);
  });""")

p("costs chart-wrap flex:none",
""".costs-scurve .chart-wrap { height: 200px; }
.costs-bydisc .chart-wrap { height: 220px; }
.costs-bywbs  .chart-wrap { height: 220px; }""",
""".costs-scurve .chart-wrap { height: 220px; flex: none; overflow: hidden; }
.costs-bydisc .chart-wrap { height: 200px; flex: none; overflow: hidden; }
.costs-bywbs  .chart-wrap { height: 200px; flex: none; overflow: hidden; }""")

p("scurve responsive:false",
"""      responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{ labels:{color: isDark?'#8ab4c4':'#3a5060',font:{size:10}} } },
      scales:{
        x:{ grid:{color:gridColor}, ticks:{color: isDark?'#5a7a8a':'#6a8090',font:{size:9}} },
        y:{ grid:{color:gridColor}, ticks:{color: isDark?'#5a7a8a':'#6a8090',font:{size:9},
            callback:v=>(v/1000).toFixed(0)+'K '+cur} }
      }
    }
  });
  }  // end if (scCvs)""",
"""      responsive:false, maintainAspectRatio:false,
      plugins:{ legend:{ labels:{color: isDark?'#8ab4c4':'#3a5060',font:{size:10}} } },
      scales:{
        x:{ grid:{color:gridColor}, ticks:{color: isDark?'#5a7a8a':'#6a8090',font:{size:9}} },
        y:{ grid:{color:gridColor}, ticks:{color: isDark?'#5a7a8a':'#6a8090',font:{size:9},
            callback:v=>(v/1000).toFixed(0)+'K '+cur} }
      }
    }
  });
  if (scCvs._chart) scCvs._chart.resize();
  }  // end if (scCvs)""")

p("bydisc responsive:false",
"      options: { responsive:true, maintainAspectRatio:false, indexAxis:'y',",
"      options: { responsive:false, maintainAspectRatio:false, indexAxis:'y',")

p("bywbs responsive:false",
"""    options: {
      responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{ labels:{color: isDark?'#8ab4c4':'#3a5060',font:{size:10}} } },
      scales:{
        x:{ grid:{display:false}, ticks:{color: isDark?'#5a7a8a':'#6a8090',font:{size:8},maxRotation:30} },
        y:{ grid:{color:gridColor}, ticks:{color: isDark?'#5a7a8a':'#6a8090',font:{size:9},
            callback:v=>(v/1000).toFixed(0)+'K'} }
      }
    }
  });
}""",
"""    options: {
      responsive:false, maintainAspectRatio:false,
      plugins:{ legend:{ labels:{color: isDark?'#8ab4c4':'#3a5060',font:{size:10}} } },
      scales:{
        x:{ grid:{display:false}, ticks:{color: isDark?'#5a7a8a':'#6a8090',font:{size:8},maxRotation:30} },
        y:{ grid:{color:gridColor}, ticks:{color: isDark?'#5a7a8a':'#6a8090',font:{size:9},
            callback:v=>(v/1000).toFixed(0)+'K'} }
      }
    }
  });
  if (wbsCvs._chart) wbsCvs._chart.resize();
}""")

p("table-scroll own scroll",
'.table-scroll { overflow-x: auto; }',
'.table-scroll { overflow-x: auto; overflow-y: auto; max-height: 440px; }')

p("costs status fallback",
"    const statusColor = {Complete:'#5ab87a','In Progress':'#e09a2a',Planned:'#607880','—':'#607880'}[it.status]||'#607880';",
"    const _st = it.status || (it.actual >= it.budget ? 'Complete' : it.actual > 0 ? 'In Progress' : 'Planned'); const statusColor = {Complete:'#5ab87a','In Progress':'#e09a2a',Planned:'#607880','—':'#607880'}[_st]||'#607880';")

ok, skip, fail = [], [], []
for name, old, new in patches:
    count = content.count(old)
    if count == 1:
        content = content.replace(old, new)
        ok.append(name)
    elif count == 0 and new in content:
        skip.append(f"{name} (already applied)")
    else:
        fail.append(f"{name} (found {count}x)")

content = content.replace("${it.status}</span></td>", "${_st}</span></td>", 1)

TARGET.write_text(content, encoding='utf-8')

print(f"patch_template.py — {TARGET}")
print(f"  {len(ok)} applied, {len(skip)} skipped (already done), {len(fail)} failed")
for n in ok:   print(f"  ✓ {n}")
for n in skip: print(f"  · {n}")
for n in fail: print(f"  ✗ {n}")
if fail: sys.exit(1)
