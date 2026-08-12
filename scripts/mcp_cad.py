#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""MCP CAD 调用助手：通过 atlisp-mcp stdio 调用 CAD 工具。
用法:
  python mcp_cad.py connect [instance]
  python mcp_cad.py eval "<lisp-code>" [instance]
  python mcp_cad.py load "<path>" [instance]
  python mcp_cad.py call <tool_name> "<json-args>" [instance]
"""
import subprocess, json, sys, threading, time, queue

MCP_CMD = ['atlisp-mcp', '--stdio', '--security-level', 'relaxed']


class MCPClient:
    def __init__(self, timeout=60):
        self.proc = subprocess.Popen(
            MCP_CMD, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=1, text=True, encoding='utf-8', errors='replace')
        self.q = queue.Queue()
        self._id = 0
        t = threading.Thread(target=self._reader, daemon=True)
        t.start()
        self._call('initialize', {
            'protocolVersion': '2024-11-05', 'capabilities': {},
            'clientInfo': {'name': 'mcp_cad', 'version': '1'}})
        time.sleep(0.5)

    def _reader(self):
        for line in self.proc.stdout:
            self.q.put(line)

    def _call(self, method, params, timeout=60):
        self._id += 1
        msg = {'jsonrpc': '2.0', 'id': self._id, 'method': method, 'params': params}
        self.proc.stdin.write(json.dumps(msg) + '\n')
        self.proc.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                line = self.q.get(timeout=2)
            except queue.Empty:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get('id') == self._id:
                return obj
        return {'error': {'message': 'timeout'}}

    def tool(self, name, arguments, timeout=120):
        r = self._call('tools/call', {'name': name, 'arguments': arguments}, timeout=timeout)
        if 'error' in r:
            return {'error': r['error']}
        result = r.get('result', {})
        content = result.get('content', [])
        texts = []
        for c in content:
            if c.get('type') == 'text':
                texts.append(c.get('text', ''))
        return {'output': '\n'.join(texts), 'isError': result.get('isError', False)}

    def close(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        self.proc.terminate()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    c = MCPClient()
    try:
        if cmd == 'connect':
            inst = sys.argv[2] if len(sys.argv) > 2 else ''
            args = {'instance': inst} if inst else {}
            r = c.tool('connect_cad', args)
            print(json.dumps(r, ensure_ascii=False))
        elif cmd == 'eval':
            code = sys.argv[2]
            args = {'code': code}
            if len(sys.argv) > 3:
                args['instance'] = sys.argv[3]
            r = c.tool('eval_lisp', args)
            print(json.dumps(r, ensure_ascii=False))
        elif cmd == 'load':
            path = sys.argv[2]
            args = {'path': path}
            if len(sys.argv) > 3:
                args['instance'] = sys.argv[3]
            r = c.tool('load_fas', args)
            print(json.dumps(r, ensure_ascii=False))
        elif cmd == 'call':
            tool, argjson = sys.argv[2], sys.argv[3]
            r = c.tool(tool, json.loads(argjson))
            print(json.dumps(r, ensure_ascii=False))
        else:
            print('unknown cmd', cmd)
    finally:
        c.close()


if __name__ == '__main__':
    main()
