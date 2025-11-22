import os
from flask import Flask, request, Response
import paramiko

app = Flask(__name__)

# 获取环境变量端口，默认8080
LISTEN_PORT = int(os.getenv('HTTP_PORT', 8080))

@app.route('/control/<path:command>', methods=['GET'])
def execute_ssh_command(command):
    # 1. 解析参数
    target_host = request.args.get('host')
    username = request.args.get('user')
    password = request.args.get('pwd')
    ssh_port = request.args.get('port', 22)

    # 2. 校验参数
    if not all([target_host, username, password]):
        return Response(
            "Error: Missing parameters. Please provide 'host', 'user', and 'pwd' in URL args.", 
            mimetype='text/plain', 
            status=400
        )

    ssh_client = paramiko.SSHClient()
    output_text = ""
    
    try:
        # 允许连接未知主机 (AutoAddPolicy)
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # 建立SSH连接
        ssh_client.connect(
            hostname=target_host, 
            port=int(ssh_port), 
            username=username, 
            password=password, 
            timeout=10
        )
        
        # 执行命令
        stdin, stdout, stderr = ssh_client.exec_command(command)
        
        # 获取输出
        out_str = stdout.read().decode('utf-8', errors='ignore')
        err_str = stderr.read().decode('utf-8', errors='ignore')
        
        # 拼接纯文本输出
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
    print(f"Starting HTTP-SSH Bridge on port {LISTEN_PORT}...")
    app.run(host='0.0.0.0', port=LISTEN_PORT)