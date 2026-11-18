"""WCAG relative-luminance calculations for final opaque token pairings."""
from pathlib import Path
import json,re
css=Path('app/static/product.css').read_text(encoding='utf-8');tokens=dict(re.findall(r'--([\w-]+):\s*(#[0-9a-fA-F]{6})\b',css))
def luminance(h):
 values=[int(h[i:i+2],16)/255 for i in [1,3,5]];linear=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in values];return sum(a*b for a,b in zip(linear,[.2126,.7152,.0722]))
def contrast(a,b):
 x,y=sorted([luminance(a),luminance(b)]);return (y+.05)/(x+.05)
pairs=[]
for fg in ['ink','muted','quiet']:
 for bg in ['canvas','chrome','surface','raised','interactive']:pairs.append((fg,bg,4.5,'normal text'))
for fg,bg in [('on-accent','accent'),('on-accent','accent-hover'),('accent','tint'),('success','success-bg'),('warning','warning-bg'),('error','error-bg'),('info','info-bg')]:pairs.append((fg,bg,4.5,'normal text'))
for bg in ['surface','raised','interactive','canvas']:pairs.extend([('control',bg,3,'control boundary'),('focus',bg,3,'focus indicator')])
result=[{'foreground':f,'foreground_hex':tokens[f],'background':b,'background_hex':tokens[b],'ratio':round(contrast(tokens[f],tokens[b]),3),'required':req,'purpose':why,'passes':contrast(tokens[f],tokens[b])>=req} for f,b,req,why in pairs]
assert all(v['passes'] for v in result),[v for v in result if not v['passes']]
Path('docs/evidence/uiux/batch9/contrast-results.json').write_text(json.dumps({'method':'WCAG2.2 sRGB relative luminance; opaque final token pairs; automated axe separately checks actual rendered states','tokens':tokens,'pairings':result},indent=2),encoding='utf-8')
print(len(result),'token pairings passed; lowest ratio',min(v['ratio'] for v in result))
