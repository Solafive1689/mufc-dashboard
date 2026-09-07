#!/usr/bin/env python3
"""bundle.py — one self-contained HTML file with every payload inlined (for previews and the
private staff export). Usage: python3 build/bundle.py [--staff] [-o preview.html]"""
import argparse, json, os, glob
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
ap=argparse.ArgumentParser(); ap.add_argument('--staff',action='store_true'); ap.add_argument('-o',default=None); a=ap.parse_args()
data={}
for f in glob.glob(os.path.join(ROOT,'data','**','*.json'),recursive=True):
    data[os.path.relpath(f,os.path.join(ROOT,'data')).replace(os.sep,'/')]=json.load(open(f,encoding='utf-8'))
if a.staff:
    for f in glob.glob(os.path.join(ROOT,'private','*.json')):
        data['private/'+os.path.basename(f)]=json.load(open(f,encoding='utf-8'))
css=open(os.path.join(ROOT,'styles.css'),encoding='utf-8').read()
js=open(os.path.join(ROOT,'src','charts.js'),encoding='utf-8').read()+'\n'+open(os.path.join(ROOT,'src','app.js'),encoding='utf-8').read()
payload=json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('</','<\\/')
html=f"""<title>MUFC · Performance{' · STAFF' if a.staff else ''}</title>
<meta charset="utf-8">
<!-- Without this a phone lays the page out at ~980px and every media query misses.
     index.html has always carried it; the preview did not, so a preview opened on a
     phone rendered the desktop layout and any mobile check against it was invalid. -->
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;700;800&family=IBM+Plex+Mono:wght@400;500&display=swap" media="print" onload="this.media='all';this.onload=null">
<style>{css}</style>
<div id="app"><div class="page" style="grid-template-columns:1fr"><p class="t-cap">Loading the season…</p></div></div>
<script>window.__DATA__={payload};window.__STAFF__={'true' if a.staff else 'false'};</script>
<script>{js}</script>"""
out=a.o or os.path.join(ROOT, 'staff-preview.html' if a.staff else 'preview.html')
open(out,'w',encoding='utf-8').write(html); print(out, f'{len(html)/1024:.0f} KB', len(data), 'payloads')
