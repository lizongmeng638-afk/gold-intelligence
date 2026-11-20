"""Build a universal Mac app using the same reviewed reference data as Streamlit.

Usage (Mac + Xcode command line tools): python mac_app/build_mac.py --output /path
No credentials, signing identities, Python runtime or user caches are bundled.
"""
import argparse
from datetime import datetime
from html import escape
import json
import math
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from gold_intelligence.gold_logic import BOE, DRIVERS, EVENTS, HISTORY_TEXT, VALUE_TEXT
from gold_intelligence.history import FIB_SOURCE, MIRROR_PAGE, WB_URL, bundled_history, event_window, fibonacci


def svg_history(rows):
    width,height,left,top,bottom=1100,420,72,25,50
    low,high=math.log10(min(r['value'] for r in rows)),math.log10(max(r['value'] for r in rows))
    def x(i):return left+i/(len(rows)-1)*(width-left-20)
    def y(v):return top+(high-math.log10(v))/(high-low)*(height-top-bottom)
    path=' '.join(f'{x(i):.2f},{y(r["value"]):.2f}' for i,r in enumerate(rows))
    shapes=[]
    for value in [30,50,100,200,500,1000,2000,5000]:
        if 10**low<=value<=10**high:
            yy=y(value)
            shapes.append(f'<line x1="{left}" y1="{yy}" x2="1080" y2="{yy}" stroke="#29364c"/><text x="5" y="{yy+5}" fill="#a9b7cc">${value:,}</text>')
    lookup={r['date'][:7]:(i,r['value']) for i,r in enumerate(rows)}
    for index in range(0,len(rows),120):
        shapes.append(f'<text x="{x(index)}" y="402" fill="#a9b7cc">{rows[index]["date"][:4]}</text>')
    for event in EVENTS:
        point=lookup.get(event['date'][:7])
        if point:
            shapes.append(f'<circle cx="{x(point[0])}" cy="{y(point[1])}" r="5" fill="#6abcff"><title>{escape(event["date"]+" "+event["title"])}</title></circle>')
    return f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="1971年至今黄金月均价，对数价格轴">'+''.join(shapes)+f'<polyline points="{path}" fill="none" stroke="#f4c76a" stroke-width="2.2"/></svg>'


def make_offline():
    data=bundled_history()
    rows=data['rows']
    info=fibonacci(rows[-60:])
    cards=''.join(f'<article><h3>{escape(d["name"])}</h3><p>{escape(d["path"])}</p><p class="muted">验证：{escape(d["check"])}</p><a href="{d["url"]}">研究来源 ↗</a></article>' for d in DRIVERS)
    events=[]
    for event in EVENTS:
        result=event_window(rows,event['date'])
        actual=(f'<p>观察窗口 {result["a"]["date"][:7]} → {result["b"]["date"][:7]}：<strong class="up" >{result["change"]:+.2%}</strong></p>' if result else '')
        if result and result['change']<0:actual=actual.replace('class="up"','class="down"')
        events.append(f'<details><summary>{event["date"]} · {escape(event["title"])}</summary><p><b>事实：</b>{escape(event["fact"])}</p><p><b>传导假设：</b>{escape(event["path"])}</p><p><b>相反力量：</b>{escape(event["counter"])}</p><p><b>验证：</b>{escape(event["check"])}</p>{actual}<a href="{event["url"]}">{escape(event["source"])} ↗</a></details>')
    levels=''.join(f'<tr><td>{r["kind"]}</td><td>{r["ratio"]:.1%}</td><td>${r["value"]:,.2f}</td></tr>' for r in info['levels'])
    a,b=info['a'],info['b']
    snapshot_time=datetime.fromisoformat(data['snapshot_retrieved_at']).strftime('%Y-%m-%d %H:%M 北京时间')
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>黄金逻辑与历史 · 离线资料</title><style>
    *{{box-sizing:border-box}}body{{margin:0;background:#0b1020;color:#e9eef7;font:16px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}}main{{max-width:1180px;padding:42px 28px;margin:auto}}h1{{font-size:34px;line-height:1.25}}h2{{margin-top:42px}}h3{{font-size:17px}}a{{color:#80c1ff}}.tag{{color:#f4c76a;letter-spacing:2px;font-size:12px}}.notice{{border-left:4px solid #f4c76a;background:#142039;padding:14px 20px}}.muted{{color:#a6b5ca;font-size:14px}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}article,details,.chart{{background:#121d30;border:1px solid #29364c;border-radius:12px;padding:18px}}details{{margin:12px 0}}summary{{cursor:pointer;font-weight:600}}table{{width:100%;border-collapse:collapse}}td,th{{padding:8px 12px;text-align:left;border-bottom:1px solid #29364c}}.up{{color:#ff5779}}.down{{color:#00e5ad}}svg{{width:100%;height:auto}}@media(max-width:700px){{.grid{{grid-template-columns:1fr}}main{{padding:24px 16px}}}} </style></head><body><main>
    <div class="tag">GOLD INTELLIGENCE · V1.4</div><h1>黄金逻辑与历史</h1><p class="notice">离线资料：历史数据截至 <b>{rows[-1]['date'][:7]}</b>，快照取得时间 {snapshot_time}。本页不联网更新，不代表当前行情。使用窗口顶部“在线分析中心”可进入完整功能。</p>
    <h2>01 / 黄金为什么有价值</h2><p>{VALUE_TEXT}</p><p>{HISTORY_TEXT}</p><p class="muted"><a href="{BOE}">英格兰银行历史说明</a> · <a href="https://www.federalreservehistory.org/essays/bretton-woods-created">布雷顿森林体系</a></p><div class="grid">{cards}</div>
    <h2>02 / 1971年以来的价格轨迹</h2><p>黄金月均价 · 名义美元/金衡盎司 · 对数价格轴 · {len(rows)}个月</p><div class="chart">{svg_history(rows)}</div><p class="muted">蓝色节点为已整理的事件，定位于事件所属月份的月均价；不是事件当天成交价。最近月份 {rows[-1]['date'][:7]}：${rows[-1]['value']:,.2f}。长期价格会经历明显回撤，历史涨幅不能外推未来。</p>
    <h2>03 / 关键节点：事实与相反力量</h2><p class="muted">已整理{len(EVENTS)}个节点；不是全部历史事件。窗口为事件前一个月到事件月后第3个月的月均价变化，包含其他因素，不能归因为事件造成的收益。</p>{''.join(events)}
    <h2>04 / 斐波那契位置快照</h2><p>使用最近60个月月均价，自动取最高与最低点后按日期排序。<b>{info['direction']}</b>：A {a['date'][:7]}（${a['value']:,.2f}）→ B {b['date'][:7]}（${b['value']:,.2f}）。最新月均基准 ${info['latest']['value']:,.2f}（{info['latest']['date'][:7]}）。</p><table><thead><tr><th>类型</th><th>比例</th><th>价格 USD/oz</th></tr></thead><tbody>{levels}</tbody></table><p class="muted">回撤 = B+(A−B)×比例；两点延伸 = A+(B−A)×倍数。50%是常用中点而非斐波那契比率。价位不是内在价值、交易建议或概率；在线版可换用近期黄金期货日线和手动选择锚点。<a href="{FIB_SOURCE}">CME 说明</a></p>
    <h2>05 / 从信息到判断</h2><p>价格口径和日期 → 实际利率、美元及风险环境 → 事件事实与相反力量 → 价格是否验证 → 技术位置与失效条件。</p>
    <h2>数据与来源</h2><p class="muted">{escape(data['source'])}。{escape(data['basis_note'])} {escape(data['snapshot_note'])}</p><p><a href="{WB_URL}">世界银行原始发布页</a> · <a href="{MIRROR_PAGE}">公开镜像和许可</a> · <a href="{data['verification_url']}">官方月报抽样核对</a></p><p class="muted">完整实时页面：<a href="https://gold-intelligence-lzm.streamlit.app/">gold-intelligence-lzm.streamlit.app</a>。打开来源链接需要联网。</p></main></body></html>'''


def build(output, skip_compile=False):
    output.mkdir(parents=True,exist_ok=True)
    app=output/'黄金智能分析中心.app'
    contents=app/'Contents'
    macos=contents/'MacOS'
    resources=contents/'Resources'
    offline=resources/'offline'
    macos.mkdir(parents=True,exist_ok=True)
    offline.mkdir(parents=True,exist_ok=True)
    executable=macos/'GoldIntelligence'
    build_dir=output/'build'
    build_dir.mkdir(exist_ok=True)
    iconset=build_dir/'GoldIcon.iconset'
    iconset.mkdir(exist_ok=True)
    master=ROOT/'assets/gold-icon-v1.4.png'
    for size in (16,32,128,256,512):
        for scale in (1,2):
            suffix='@2x' if scale==2 else ''
            filename=iconset/f'icon_{size}x{size}{suffix}.png'
            subprocess.run(['sips','-z',str(size*scale),str(size*scale),str(master),'--out',str(filename)],check=True,stdout=subprocess.DEVNULL)
    subprocess.run(['sips','-s','format','icns',str(iconset/'icon_512x512.png'),'--out',str(resources/'GoldIcon.icns')],check=True,stdout=subprocess.DEVNULL)
    if not skip_compile:
        for architecture in ['arm64','x86_64']:
            subprocess.run(['xcrun','swiftc','-O','-module-cache-path',str(build_dir/'module-cache'),'-target',architecture+'-apple-macos12.0',str(ROOT/'mac_app/GoldIntelligence.swift'),'-o',str(build_dir/architecture)],check=True)
        subprocess.run(['lipo','-create',str(build_dir/'arm64'),str(build_dir/'x86_64'),'-output',str(executable)],check=True)
    elif not executable.exists():
        raise FileNotFoundError(executable)
    plist={'CFBundleName':'GOLD INTELLIGENCE','CFBundleDisplayName':'黄金智能分析中心','CFBundleIdentifier':'local.goldintelligence.desktop',
           'CFBundleExecutable':'GoldIntelligence','CFBundlePackageType':'APPL','CFBundleShortVersionString':'1.4.0','CFBundleVersion':'140','CFBundleIconFile':'GoldIcon.icns',
           'LSMinimumSystemVersion':'12.0','NSHighResolutionCapable':True,'NSPrincipalClass':'NSApplication'}
    (contents/'Info.plist').write_bytes(plistlib.dumps(plist))
    (offline/'index.html').write_text(make_offline(),encoding='utf-8')
    for filename in ['gold_monthly.csv','gold_monthly_metadata.json','gold_events.json']:
        shutil.copy2(ROOT/'data/reference'/filename,offline/filename)
    subprocess.run(['codesign','--force','--sign','-',str(app)],check=True)
    print(app)
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--skip-compile',action='store_true')
    args=parser.parse_args()
    build(args.output.resolve(),args.skip_compile)
