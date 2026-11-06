"""商汤接口本地代理。

浏览器直接调商汤会被 CORS 预检拦住（OPTIONS 返回 404），中间加一层转发就没问题。
用法：双击 start-proxy.bat，窗口别关；网页里 Base URL 填 http://127.0.0.1:8890/v1。
"""

import json
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = 'https://token.sensenova.cn/v1'
PORT = 8890


class Handler(BaseHTTPRequestHandler):

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        self._forward('GET', None)

    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0) or 0)
        body = self.rfile.read(n) if n else b''
        self._forward('POST', body)

    def _forward(self, method, body):
        path = self.path
        if path.startswith('/v1'):
            url = UPSTREAM + path[3:]
        else:
            url = UPSTREAM + path

        headers = {}
        auth = self.headers.get('Authorization')
        if auth:
            headers['Authorization'] = auth
        if body:
            headers['Content-Type'] = 'application/json'

        req = urllib.request.Request(url, data=body, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
                status = resp.status
                ctype = resp.headers.get('Content-Type', 'application/json')
        except urllib.error.HTTPError as e:
            data = e.read()
            status = e.code
            ctype = e.headers.get('Content-Type', 'application/json')
        except Exception as e:
            data = json.dumps({'error': {'message': str(e)}}, ensure_ascii=False).encode()
            status = 502
            ctype = 'application/json'

        self.send_response(status)
        self._cors()
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        print('  %s %s' % (self.command, self.path.split('?')[0]), flush=True)


if __name__ == '__main__':
    print('商汤代理已启动：http://127.0.0.1:%d/v1' % PORT)
    print('网页里 Base URL 填这个地址，Key 填商汤的 key。关掉窗口即停止。')
    ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
