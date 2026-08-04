"""MCP CAD 交互辅助：连接/执行/查询，供开发调试使用。

用法：
    python -m tools.cad_probe info                    # 连接信息
    python -m tools.cad_probe eval "(+ 1 2)"          # 执行 Lisp
    python -m tools.cad_probe load <file.fas>         # 加载并验证
"""
import json
import subprocess
import sys


class CadClient:
    def __init__(self):
        self.proc = subprocess.Popen(
            ["atlisp-mcp", "--stdio", "--security-level", "relaxed"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=1, text=True, encoding="utf-8", errors="replace",
        )
        self._id = 0
        self._call("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "atlispcc-dev", "version": "0.1"},
        })

    def _call(self, method, params):
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("MCP 进程退出")
            data = json.loads(line)
            if data.get("id") == self._id:
                if "error" in data:
                    raise RuntimeError(f"MCP error: {data['error']}")
                return data.get("result")

    def tool(self, name, **args):
        return self._call("tools/call", {"name": name, "arguments": args})

    def connect(self):
        res = self.tool("connect_cad")
        return res

    def info(self):
        return self.tool("get_cad_info")

    def eval(self, code):
        return self.tool("eval_lisp_with_result", code=code)

    def close(self):
        self.proc.terminate()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "info"
    c = CadClient()
    try:
        if cmd == "info":
            print(json.dumps(c.info(), ensure_ascii=False))
        elif cmd == "connect":
            print(json.dumps(c.connect(), ensure_ascii=False))
        elif cmd == "eval":
            print(json.dumps(c.eval(sys.argv[2]), ensure_ascii=False))
        elif cmd == "load":
            # CAD 只能从支持路径 findfile/load，先拷贝到 @lisp 目录
            import os
            import shutil
            src = sys.argv[2]
            dst_dir = "C:/Users/vitalgg/@lisp"
            name = os.path.basename(src)
            dst = os.path.join(dst_dir, name)
            shutil.copy2(src, dst)
            try:
                print(json.dumps(c.eval(f'(load "{dst}")'), ensure_ascii=False))
            finally:
                os.unlink(dst)
    finally:
        c.close()


if __name__ == "__main__":
    main()
