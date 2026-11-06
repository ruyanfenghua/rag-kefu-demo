# -*- coding: utf-8 -*-
"""读 评测结果.json，按 评测集.jsonl 的标注算指标，生成 评测报告.md。"""
import json
import pathlib
import sys
import math

BASE = pathlib.Path(__file__).parent
res = json.loads((BASE / '评测结果.json').read_text(encoding='utf-8'))
items = {x['id']: x for x in res['items']}
ret = {x['id']: x for x in res['retrieval']}
gen = {x['id']: x for x in res['generation']}
meta = res['meta']

REFUSE_HINTS = ['查不到', '没有找到', '资料里没有', '不确定', '无法确认',
                '这边查不到', '不清楚', '没法', '不能帮', '转人工', '联系人工',
                '没有相关规定', '没有相关信息', '资料中没有']


def norm(s):
    return ''.join(str(s or '').split())


def hit(top, item):
    """单块是否命中标注的文档与小节。"""
    if not top or not item['expected_doc']:
        return False
    d = item['expected_doc'] in (top.get('doc') or '')
    s = (not item['expected_section']) or item['expected_section'] in (top.get('section') or '')
    return d and s


def doc_hit(top, item):
    return bool(top) and item['expected_doc'] in (top.get('doc') or '')


def key_cover(item, reply):
    kps = item.get('key_points') or []
    if not kps:
        return None
    r = norm(reply)
    n = sum(1 for k in kps if norm(k) in r)
    return n / len(kps), n, len(kps)


def pct(x):
    return ('%.1f%%' % (x * 100))


def quantile(vals, p):
    if not vals:
        return 0.0
    v = sorted(vals)
    k = (len(v) - 1) * p
    f, c = math.floor(k), math.ceil(k)
    return v[f] if f == c else v[f] + (v[c] - v[f]) * (k - f)


# 检索侧：只统计有标注答案的题
ret_ids = [i for i in items if items[i]['expected_doc']]
rows = []
for i in ret_ids:
    tops = ret[i]['top']
    first = next((n for n, t in enumerate(tops, 1) if hit(t, items[i])), 0)
    rows.append({'id': i, 'q': items[i]['question'], 'type': items[i]['question_type'],
                 'expect': items[i]['expected_doc'] + (' · ' + items[i]['expected_section'] if items[i]['expected_section'] else ''),
                 'top1': (tops[0]['doc'] + ' · ' + tops[0]['section'] + ' ' + str(tops[0]['sim']) + '%') if tops else '无',
                 'first': first, 'top1_ok': first == 1, 'hit3': 0 < first <= 3,
                 'hit5': 0 < first <= 5, 'doc1': doc_hit(tops[0] if tops else None, items[i])})

n = len(rows)
hit1 = sum(r['top1_ok'] for r in rows)
hit3 = sum(r['hit3'] for r in rows)
hit5 = sum(r['hit5'] for r in rows)
doc1 = sum(r['doc1'] for r in rows)
mrr = sum(1 / r['first'] for r in rows if r['first']) / n

# 生成侧
gen_rows = []
for i, g in gen.items():
    it = items[i]
    kc = key_cover(it, g['reply'])
    refused = any(norm(h) in norm(g['reply']) for h in REFUSE_HINTS)
    gen_rows.append({'id': i, 'q': it['question'], 'sec': g['sec'],
                     'genSec': g.get('genSec', ''), 'kc': kc, 'refused': refused,
                     'err': g['err'], 'typing': g['typing'], 'btn': g['btn'],
                     'reply': g['reply'], 'hits': g['hits'], 'rw': g['rw']})

ans_rows = [r for r in gen_rows if items[r['id']]['answerable']]
noans_rows = [r for r in gen_rows if not items[r['id']]['answerable']]
cover_vals = [r['kc'][0] for r in ans_rows if r['kc'] is not None]
full_cover = sum(1 for r in ans_rows if r['kc'] and r['kc'][0] == 1.0)
refuse_ok = sum(r['refused'] for r in noans_rows)
secs = [r['sec'] for r in gen_rows]
multi = [r for r in gen_rows if items[r['id']]['group'] and items[r['id']]['order'] == 2]
fail_rows = [r for r in gen_rows if r['err'] or r['typing'] or r['btn']]

bad = [r for r in rows if not r['top1_ok']]
bad_gen = [r for r in ans_rows if r['kc'] is not None and r['kc'][0] < 1.0]

L = []
L.append('# RAG 客服演示 · 评测报告')
L.append('')
L.append('生成时间：%s' % meta['time'])
L.append('')
L.append('## 一、口径')
L.append('')
L.append('- 被测对象：`rag-demo.html`，8 份文档、%d 块，切块窗口 %s 字、重叠 %s 字。' % (meta['chunks'], meta['chunkSize'], meta['overlap']))
L.append('- 向量模型：%s（%s 维）；对话模型：%s；接口：%s；查询改写：%s。' % (meta['vecModel'], meta['vecDim'], meta['chatModel'], meta['chatBase'], '开' if meta['rw'] else '关'))
L.append('- 评测集：%d 条，其中 %d 条有标注答案，%d 条为无答案/越权题。检索侧跑 %d 条，生成侧端到端跑 %d 条。' % (len(items), len(ret_ids), len(items) - len(ret_ids), len(ret), len(gen)))
L.append('- 检索侧用原句调用页面里的 `rank(q)`，取前 5 块；命中判定为「文档标题匹配 且 小节名包含标注关键词」。查询改写单独在生成侧生效。')
L.append('- 生成侧端到端调用 `run()`：查询改写 → 检索 → 证据判定 → （不足时补关键词重查再判定）→ 生成。每题前重置会话，多轮组首问重置、追问不重置。')
L.append('- 要点覆盖率为规则判定：标注的关键词去掉空格后是否出现在回复里。')
L.append('- 知识库 8 份文档为虚构样例。延迟为本机实测，含多次串行的模型调用。')
L.append('- 样本量 %d 条。' % len(items))
L.append('')
L.append('## 二、检索侧')
L.append('')
L.append('| 指标 | 结果 | 计算方式 |')
L.append('| --- | --- | --- |')
L.append('| Hit@1 | %d / %d = %s | Top1 命中标注文档与小节 |' % (hit1, n, pct(hit1 / n)))
L.append('| Hit@3 | %d / %d = %s | 前 3 块中至少一块命中 |' % (hit3, n, pct(hit3 / n)))
L.append('| Hit@5 | %d / %d = %s | 前 5 块中至少一块命中 |' % (hit5, n, pct(hit5 / n)))
L.append('| 文档命中@1 | %d / %d = %s | Top1 只看文档标题，不看小节 |' % (doc1, n, pct(doc1 / n)))
L.append('| MRR | %.3f | 首个正确结果排名的倒数平均，未命中记 0 |' % mrr)
L.append('')
L.append('| 编号 | 问题 | 期望命中 | 实际 Top1 | 首个命中排名 |')
L.append('| --- | --- | --- | --- | --- |')
for r in rows:
    L.append('| %s | %s | %s | %s | %s |' % (r['id'], r['q'], r['expect'], r['top1'], r['first'] or '未命中'))
L.append('')
L.append('## 三、生成侧')
L.append('')
L.append('| 指标 | 结果 |')
L.append('| --- | --- |')
if cover_vals:
    L.append('| 平均要点覆盖率 | %s（%d 条有标注要点的可答题） |' % (pct(sum(cover_vals) / len(cover_vals)), len(cover_vals)))
    L.append('| 要点全覆盖题数 | %d / %d |' % (full_cover, len(cover_vals)))
L.append('| 拒答/不编造 | %d / %d（无答案与越权题） |' % (refuse_ok, len(noans_rows)))
L.append('| 多轮追问 | %d 条，逐条见下表 |' % len(multi))
L.append('| 端到端延迟 | 平均 %.1f 秒，P50 %.1f 秒，P95 %.1f 秒，最快 %.1f 秒，最慢 %.1f 秒 |' % (sum(secs) / len(secs), quantile(secs, .5), quantile(secs, .95), min(secs), max(secs)))
L.append('| 调用失败 | %d 条（报错、三点动画残留、按钮未恢复） |' % len(fail_rows))
L.append('')
L.append('注：Q17 的回复是「需要先确认身份和权限，请问您是企业的超级管理员吗」，没有出现词表里的拒答词，规则记为未拒答。逐条看内容，它没有执行操作、也没有编造数据，属于规则漏判。')
L.append('')
L.append('| 编号 | 问题 | 耗时 | 要点命中 | 回复摘要 |')
L.append('| --- | --- | --- | --- | --- |')
for r in gen_rows:
    kc = '—' if r['kc'] is None else '%d/%d' % (r['kc'][1], r['kc'][2])
    refuse = '，含拒答表述' if r['refused'] else ''
    L.append('| %s | %s | %.1f 秒 | %s%s | %s |' % (r['id'], r['q'], r['sec'], kc, refuse, norm(r['reply'])[:70]))
L.append('')
L.append('## 四、多轮追问')
L.append('')
for r in multi:
    it = items[r['id']]
    L.append('- **%s %s**：期望承接「%s」的主题，命中 `%s · %s`。要点 %s。回复：%s' % (
        r['id'], r['q'],
        items[it['group'] + 'a']['question'] if it['group'] + 'a' in items else it['group'],
        it['expected_doc'], it['expected_section'],
        ('%d/%d' % (r['kc'][1], r['kc'][2])) if r['kc'] else '—',
        norm(r['reply'])[:120]))
    if r['hits']:
        L.append('  - Top1：%s' % (r['hits'][0]['src'] + ' ' + r['hits'][0]['sim']))
    if norm(r['rw']):
        stale = norm('原问题：' + r['q']) not in norm(r['rw'])
        txt = ('未采用改写（显示为 %s）' % norm(r['rw'])[:60]) if stale else norm(r['rw'])[:80]
        L.append('  - 查询改写：%s' % txt)
L.append('')
L.append('## 五、未达标样例')
L.append('')
L.append('检索侧 Top1 未命中 %d 条：' % len(bad))
L.append('')
if bad:
    L.append('| 编号 | 问题 | 期望 | 实际 Top1 |')
    L.append('| --- | --- | --- | --- |')
    for r in bad:
        L.append('| %s | %s | %s | %s |' % (r['id'], r['q'], r['expect'], r['top1']))
else:
    L.append('无。')
L.append('')
L.append('生成侧要点未全覆盖 %d 条：' % len(bad_gen))
L.append('')
if bad_gen:
    L.append('| 编号 | 问题 | 缺的要点 | 回复摘要 |')
    L.append('| --- | --- | --- | --- |')
    for r in bad_gen:
        miss = [k for k in items[r['id']]['key_points'] if norm(k) not in norm(r['reply'])]
        L.append('| %s | %s | %s | %s |' % (r['id'], r['q'], '、'.join(miss), norm(r['reply'])[:80]))
else:
    L.append('无。')
L.append('')
L.append('## 六、已知问题')
L.append('')
L.append('- 多轮省略追问：M01b「多久到」在生成侧命中「三、退款到账时间」77.3%，回复给出各支付方式的退款到账时间，未承接上一轮的发票主题。该轮改写未采用，检索按原句进行。')
L.append('- `#rw` 在改写为空时只隐藏、不清内容，运维侧会读到上一题的改写文本。')
L.append('- 检索侧 Top1 未命中 4 条，生成侧要点未全覆盖 3 条，逐条见第五节。')
L.append('')
L.append('## 七、复现')
L.append('')
L.append('启动 `start-proxy.bat`，确认 8890 在监听，再执行：')
L.append('')
L.append('```')
L.append('node eval/评测脚本.js <临时目录> <页面副本.html> eval/评测结果.json')
L.append('python eval/生成报告.py')
L.append('```')
L.append('')
L.append('原始数据：`eval/评测结果.json`（含逐题回复、命中块、耗时、改写文本）。标注：`eval/评测集.jsonl`。')

OUT = BASE.parent / 'docs' / '评测报告.md'
OUT.write_text('\n'.join(L) + '\n', encoding='utf-8')
print('已生成 docs/评测报告.md，检索 %d 题、生成 %d 题' % (len(ret), len(gen)))
