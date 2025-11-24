import os
from flask import Flask, request, Response
import paramiko

app = Flask(__name__)

# 从环境变量获取监听端口，默认 8080
LISTEN_PORT = int(os.getenv('HTTP_PORT', 8080))

# --- 新增：首页帮助信息 ---
@app.route('/')
def index():
    # 动态获取当前访问的 "IP:端口" (例如 192.168.110.5:9091)
    base_url = request.host
    
    help_text = f"""SSH远程控制网关 (url-to-ssh)
API[GET]: http://{base_url}/control/<Command>
Params:
  host    : 目标设备的IP地址 (必须),
  user    : SSH登录用户名 (必须),
  pwd     : SSH登录密码 (必须),
  port    : 目标设备的SSH端口 (默认: 22),
Example: http://{base_url}/control/ls -la?host=192.168.1.100&user=root&pwd=password
"""
    return Response(help_text, mimetype='text/plain')

# --- 原有逻辑：SSH 执行 ---
@app.route('/control/<path:command>', methods=['GET'])
def execute_ssh_command(command):
    # 1. 获取连接参数
    target_host = request.args.get('host')
    username = request.args.get('user')
    password = request.args.get('pwd')
    ssh_port = request.args.get('port', 22) # SSH端口默认还是22

    # 2. 检查参数是否齐全
    if not all([target_host, username, password]):
        return Response(
            "[Error] Missing parameters. Please check: host, user, pwd", 
            mimetype='text/plain', 
            status=400
        )

    ssh_client = paramiko.SSHClient()
    output_text = ""
    
    try:
        # 允许连接未知主机
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # 连接
        ssh_client.connect(
            hostname=target_host, 
            port=int(ssh_port), 
            username=username, 
            password=password, 
            timeout=10
        )
        
        # 执行命令
        stdin, stdout, stderr = ssh_client.exec_command(command)
        
        # 读取结果
        out_str = stdout.read().decode('utf-8', errors='ignore')
        err_str = stderr.read().decode('utf-8', errors='ignore')
        
        # 格式化输出
        output_text += f"[{username}@{target_host}] exec: {command}\n"
        output_text += "=" * 40 + "\n"
        
        if out_str:
            output_text += out_str
        if err_str:
            output_text += "\n[STDERR]:\n" + err_str
            
    except Exception as e:
        output_text += f"[Connection Failed]: {str(e)}"
    finally:
        ssh_client.close()

    # 返回纯文本
    return Response(output_text, mimetype='text/plain')

if __name__ == '__main__':
    print(f"Server starting on port {LISTEN_PORT}...")
    app.run(host='0.0.0.0', port=LISTEN_PORT)