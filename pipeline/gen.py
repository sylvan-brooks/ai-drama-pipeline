"""异步生成任务: 图 / 视频 / 配音. 提交 → 轮询 → 先记账再下载, 防重复花钱.
接的是"提交任务拿 taskId, 再按 taskId 查结果"这一类接口; 地址、模型名、单价、返回字段都写在 providers.json 里.
python gen.py img   <name> <prompt.txt|"文字"> [--model 名字] [--w 864 --h 1536 --seed N]
python gen.py video <name> <prompt.txt> --ref <name|url|本地图> ... [--audio ...] [--dur 15 --res 480p --ratio 9:16]
python gen.py tts   <name> <text.txt|"文字"> --voice <音色 ID>
python gen.py balance | fetch <name> | ledger
环境变量: GEN_API_KEY (必填) · GEN_BASE_URL (可选, 盖过 providers.json 的 base) · HTTPS_PROXY (要代理才设).
--root 是工作目录 (默认当前目录): 产物放 <root>/gen/<kind>/<name>.<ext>, 账本 <root>/ledger.jsonl.
同名已成功的不重复提交 (要重来换个 name); 提交后先把结果地址记进账本再下载, 下载挂了用 fetch 重下, 不再花钱.
退出码: 0 成功 / 1 参数或配置问题 / 2 提交、生成或下载失败."""
import sys, os, json, time, argparse, base64, io, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
EXT = {'img': 'png', 'video': 'mp4', 'tts': 'wav'}
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36'}
OPEN = urllib.request.build_opener()   # 默认就会读 HTTPS_PROXY / HTTP_PROXY 环境变量


def die(msg, code=1):
    print(msg, file=sys.stderr); sys.exit(code)


def pick(obj, path):
    """按 "data.taskId" 这样的点路径取值, 取不到返回 None."""
    for k in path.split('.'):
        if not isinstance(obj, dict) or k not in obj:
            return None
        obj = obj[k]
    return obj


def load_cfg(path):
    if not os.path.isfile(path):
        die(f'找不到 {path}; 照 providers.example.json 写一份')
    c = json.load(open(path, encoding='utf-8'))
    c['base'] = (os.environ.get('GEN_BASE_URL') or c.get('base', '')).rstrip('/')
    if not c['base']:
        die('providers.json 里没有 base, 也没设 GEN_BASE_URL')
    return c


def req(key, url, body=None, timeout=120):
    r = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                               headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
                               method='POST' if body is not None else 'GET')
    try:
        with OPEN.open(r, timeout=timeout) as f:
            return f.status, json.loads(f.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')[:600]   # 只留响应正文开头, 不打印请求头 (里面有 key)


class Ledger:
    def __init__(self, root):
        self.path = os.path.join(root, 'ledger.jsonl')

    def all(self):
        if not os.path.exists(self.path):
            return []
        return [json.loads(l) for l in open(self.path, encoding='utf-8') if l.strip()]

    def log(self, rec):
        with open(self.path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def resolve(x, ledger):
    """本地文件 → base64 (图片转 JPEG 92 压体积); url 原样; 其它当成账本里的 name, 取它的结果 url."""
    if os.path.isfile(x):
        if x.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
            from PIL import Image
            buf = io.BytesIO(); Image.open(x).convert('RGB').save(buf, 'JPEG', quality=92)
            return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()
        mime = 'audio/wav' if x.lower().endswith('.wav') else 'audio/mpeg'
        return f'data:{mime};base64,' + base64.b64encode(open(x, 'rb').read()).decode()
    if x.startswith('http'):
        return x
    for r in reversed(ledger.all()):
        if r.get('name') == x and r.get('urls'):
            return r['urls'][0]
    die(f'账本里没有 {x} 的结果')


def text_arg(s):
    if os.path.isfile(s):
        return open(s, encoding='utf-8').read().strip()
    if s.endswith('.txt') or '/' in s or chr(92) in s:
        die(f'提示词文件不存在: {s}')
    return s


def download(url, out):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    last = None
    # 结果地址有时走代理下不动、有时不走代理下不动, 两条路各试一次
    for op in (OPEN, urllib.request.build_opener(urllib.request.ProxyHandler({}))):
        try:
            data = op.open(urllib.request.Request(url, headers=UA), timeout=300).read()
            with open(out + '.part', 'wb') as f:
                f.write(data)
            os.replace(out + '.part', out); return
        except Exception as e:
            last = e
    raise last


def estimate(cfg, model, kind, a, text=''):
    """按 providers.json 里的单价估花费; 没写单价就返回 None. 只是估算, 以服务商后台扣费为准."""
    p = cfg.get('models', {}).get(model, {}).get('price', {})
    if kind == 'img' and 'per_image' in p:
        return p['per_image']
    if kind == 'video' and 'per_second' in p:
        rate = p['per_second'].get(a.res) if isinstance(p['per_second'], dict) else p['per_second']
        return None if rate is None else a.dur * rate
    if kind == 'tts' and 'per_kbyte' in p:
        return max(p.get('min_bytes', 0), len(text.encode('utf-8'))) / 1000 * p['per_kbyte']
    return None


def build_body(cfg, kind, model, prompt, a, ledger):
    """请求体. 字段名按常见写法给的, 和你的服务商文档对不上就改这里; 模型专属参数写在 providers.json 的 extra 里."""
    if kind == 'img':
        body = {'model': model, 'prompt': prompt, 'width': a.w, 'height': a.h}
        if a.seed is not None:
            body['seed'] = a.seed
    elif kind == 'video':
        body = {'model': model, 'prompt': prompt, 'duration': a.dur, 'resolution': a.res, 'ratio': a.ratio,
                'images': [resolve(x, ledger) for x in a.ref]}
        if a.audio:
            body['audio_list'] = [resolve(x, ledger) for x in a.audio]
    else:
        if not a.voice:
            die('tts 要 --voice <音色 ID>')
        body = {'model': model, 'text': prompt, 'reference_id': a.voice, 'format': 'wav'}
    body.update(cfg.get('models', {}).get(model, {}).get('extra', {}))
    return body


def main():
    ap = argparse.ArgumentParser(description='异步生成任务 (先记账再下载)')
    ap.add_argument('kind', choices=['img', 'video', 'tts', 'balance', 'fetch', 'ledger'])
    ap.add_argument('name', nargs='?'); ap.add_argument('prompt', nargs='?')
    ap.add_argument('--root', default='.'); ap.add_argument('--config', default=os.path.join(HERE, 'providers.json'))
    ap.add_argument('--model')
    ap.add_argument('--w', type=int, default=864); ap.add_argument('--h', type=int, default=1536); ap.add_argument('--seed', type=int)
    ap.add_argument('--ref', action='append', default=[]); ap.add_argument('--audio', action='append', default=[])
    ap.add_argument('--dur', type=int, default=15); ap.add_argument('--res', default='480p'); ap.add_argument('--ratio', default='9:16')
    ap.add_argument('--voice'); ap.add_argument('--timeout', type=int, default=1800); ap.add_argument('--poll', type=float)
    a = ap.parse_args()
    root = os.path.abspath(a.root); os.makedirs(root, exist_ok=True)
    ledger = Ledger(root)
    if a.kind == 'ledger':   # 账本汇总: 每个模型提交了几次、估算花了多少
        tot = {}
        for r in ledger.all():
            if r.get('state') == 'submitted':
                m = tot.setdefault(r['model'], [0, 0.0]); m[0] += 1; m[1] += r.get('cost_est') or 0
        for m, (n, c) in tot.items():
            print(f'{m}: 提交 {n} 次, 估算 {c:.3f}')
        return
    cfg = load_cfg(a.config)
    key = os.environ.get('GEN_API_KEY', '').strip()
    if not key:
        die('先设环境变量 GEN_API_KEY')
    ep, rs = cfg.get('endpoints', {}), cfg.get('response', {})
    def balance():
        if 'balance' not in ep:
            return '?'
        c, r = req(key, cfg['base'] + ep['balance'], timeout=20)
        return pick(r, rs.get('balance', 'data.balance')) if c == 200 else f'? (HTTP {c})'
    if a.kind == 'balance':
        print('余额', balance()); return
    if not a.name:
        die('要给 name')
    if a.kind == 'fetch':   # 重新下载账本里 name 的结果 (下载失败时用, 不再花钱)
        recs = [x for x in ledger.all() if x.get('name') == a.name and x.get('urls')]
        if not recs:
            die(f'账本里没有 {a.name} 的结果地址')
        r = recs[-1]; out = os.path.join(root, 'gen', r['kind'], f"{a.name}.{EXT[r['kind']]}")
        try:
            download(r['urls'][0], out)
        except Exception as e:
            die(f'下载失败: {type(e).__name__} (结果地址可能已过期)', 2)
        r['file'] = out; r['state'] = 'completed'; ledger.log(r); print(out); return
    done = [r for r in ledger.all() if r.get('name') == a.name and r.get('state') == 'completed']
    if done:
        print(f'{a.name} 已经生成过: {done[-1]["file"]} (要重来换个 name)'); return
    if not a.prompt:
        die('要给提示词 (文字或 .txt 文件)')
    prompt = text_arg(a.prompt)
    model = a.model or cfg.get('defaults', {}).get(a.kind)
    if not model:
        die(f'没给 --model, providers.json 的 defaults 里也没有 {a.kind}')
    body = build_body(cfg, a.kind, model, prompt, a, ledger)
    cost = estimate(cfg, model, a.kind, a, prompt)
    print(f'{a.kind} {a.name} · {model} · 预估 {"?" if cost is None else f"{cost:.3f}"} · 余额 {balance()}', flush=True)
    c, r = req(key, cfg['base'] + ep[a.kind], body)
    tid = pick(r, rs.get('task_id', 'data.taskId')) if c == 200 else None
    if not tid:
        ledger.log({'name': a.name, 'kind': a.kind, 'model': model, 'state': 'submit_failed', 'err': str(r)[:300], 't': time.time()})
        die(f'提交失败 HTTP {c}: {str(r)[:300]}', 2)
    t0 = time.time()
    ledger.log({'name': a.name, 'kind': a.kind, 'model': model, 'state': 'submitted', 'taskId': tid,
                'cost_est': None if cost is None else round(cost, 4), 't': t0})
    done_states, fail_states = set(rs.get('done', ['completed'])), set(rs.get('failed', ['failed', 'error']))
    poll = a.poll or (6 if a.kind == 'img' else 20)
    while True:
        time.sleep(poll)
        c, r = req(key, f"{cfg['base']}{ep[a.kind]}?task_id={tid}")
        st = pick(r, rs.get('state', 'data.state'))
        if st in done_states | fail_states or time.time() - t0 > a.timeout:
            break
        print(f'  {st} {time.time() - t0:.0f}s', flush=True)
    urls = next((u if isinstance(u, list) else [u] for u in (pick(r, p) for p in rs.get('urls', ['data.resultUrls'])) if u), [])
    meta = {k: (v if k not in ('images', 'audio_list') else [u[:60] for u in v]) for k, v in body.items() if k not in ('prompt', 'text')}
    rec = {'name': a.name, 'kind': a.kind, 'model': model, 'cost_est': None if cost is None else round(cost, 4), 'taskId': tid,
           'state': st, 'secs': round(time.time() - t0), 'meta': meta, 'prompt': prompt, 'urls': urls, 't': time.time()}
    if st not in done_states or not urls:
        rec['err'] = str(r)[:400]; ledger.log(rec); die(f'没成功: {st} {str(r)[:300]}', 2)
    out = os.path.join(root, 'gen', a.kind, f'{a.name}.{EXT[a.kind]}')
    rec['state'] = 'generated'; ledger.log(rec)          # 先记 url, 下载挂了也能 fetch
    try:
        download(urls[0], out)
    except Exception as e:
        die(f'下载失败: {type(e).__name__}; 结果地址已记账, 跑 `gen.py fetch {a.name}` 重下', 2)
    rec['file'] = out; rec['state'] = 'completed'; ledger.log(rec)
    print(f'{out}  {rec["secs"]}s · 余额 {balance()}')


if __name__ == '__main__':
    main()
