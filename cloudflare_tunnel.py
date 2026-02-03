#!/usr/bin/env python3
"""
Cloudflare Tunnel 自动化脚本
用于在 GitHub Actions 中自动创建和管理 Cloudflare Tunnel
"""

import os
import sys
import json
import time
import logging
import subprocess
import requests
from typing import Optional, Dict, Any
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

class CloudflareTunnelManager:
    def __init__(self, cf_token: str = None):
        self.cf_token = cf_token or os.getenv('CF_TOKEN')
        if not self.cf_token:
            raise ValueError("CF_TOKEN 环境变量未设置")
        
        self.tunnel_name = f"github-actions-tunnel-{int(time.time())}"
        self.config_dir = Path.home() / ".cloudflared"
        self.config_file = self.config_dir / "config.yml"
        
    def install_cloudflared(self) -> bool:
        """安装 cloudflared 客户端"""
        try:
            logger.info("安装 cloudflared...")
            
            # 检查是否已安装
            result = subprocess.run(['which', 'cloudflared'], capture_output=True, text=True)
            if result.returncode == 0:
                logger.info("cloudflared 已安装")
                return True
            
            # 安装 cloudflared
            install_cmd = """
            wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O /tmp/cloudflared
            sudo chmod +x /tmp/cloudflared
            sudo mv /tmp/cloudflared /usr/local/bin/cloudflared
            """
            
            result = subprocess.run(install_cmd, shell=True, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"安装 cloudflared 失败: {result.stderr}")
                return False
            
            logger.info("cloudflared 安装成功")
            return True
            
        except Exception as e:
            logger.error(f"安装 cloudflared 时出错: {e}")
            return False
    
    def create_tunnel(self) -> Optional[str]:
        """创建 Cloudflare Tunnel"""
        try:
            logger.info(f"创建 Cloudflare Tunnel: {self.tunnel_name}")
            
            # 创建配置目录
            self.config_dir.mkdir(exist_ok=True)
            
            # 创建隧道
            cmd = f"cloudflared tunnel create {self.tunnel_name}"
            env = os.environ.copy()
            env['CF_API_TOKEN'] = self.cf_token
            
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, env=env)
            if result.returncode != 0:
                logger.error(f"创建隧道失败: {result.stderr}")
                return None
            
            # 提取隧道 ID
            tunnel_id = None
            for line in result.stdout.split('\n'):
                if 'Created tunnel' in line and 'with id' in line:
                    parts = line.split('with id')
                    if len(parts) > 1:
                        tunnel_id = parts[1].strip().split()[0]
                        break
            
            if not tunnel_id:
                logger.error("无法提取隧道 ID")
                return None
            
            logger.info(f"隧道创建成功: {tunnel_id}")
            return tunnel_id
            
        except Exception as e:
            logger.error(f"创建隧道时出错: {e}")
            return None
    
    def configure_tunnel(self, tunnel_id: str, local_url: str = "http://localhost:7860") -> bool:
        """配置隧道"""
        try:
            logger.info(f"配置隧道 {tunnel_id}，本地地址: {local_url}")
            
            config = {
                'tunnel': tunnel_id,
                'credentials-file': str(self.config_dir / f"{tunnel_id}.json"),
                'ingress': [
                    {
                        'hostname': '*',
                        'service': local_url
                    },
                    {
                        'service': 'http_status:404'
                    }
                ]
            }
            
            # 保存配置文件
            with open(self.config_file, 'w') as f:
                yaml_content = self._dict_to_yaml(config)
                f.write(yaml_content)
            
            logger.info(f"配置文件已保存: {self.config_file}")
            return True
            
        except Exception as e:
            logger.error(f"配置隧道时出错: {e}")
            return False
    
    def _dict_to_yaml(self, data: Dict, indent: int = 0) -> str:
        """将字典转换为 YAML 格式"""
        yaml_str = ""
        indent_str = "  " * indent
        
        for key, value in data.items():
            if isinstance(value, dict):
                yaml_str += f"{indent_str}{key}:\n{self._dict_to_yaml(value, indent + 1)}"
            elif isinstance(value, list):
                yaml_str += f"{indent_str}{key}:\n"
                for item in value:
                    if isinstance(item, dict):
                        yaml_str += f"{indent_str}  -\n{self._dict_to_yaml(item, indent + 2)}"
                    else:
                        yaml_str += f"{indent_str}  - {item}\n"
            else:
                yaml_str += f"{indent_str}{key}: {value}\n"
        
        return yaml_str
    
    def run_tunnel(self) -> Optional[subprocess.Popen]:
        """运行隧道"""
        try:
            logger.info("启动 Cloudflare Tunnel...")
            
            cmd = f"cloudflared tunnel --config {self.config_file} run"
            env = os.environ.copy()
            env['CF_API_TOKEN'] = self.cf_token
            
            process = subprocess.Popen(
                cmd, 
                shell=True, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True,
                env=env
            )
            
            # 等待隧道启动
            time.sleep(5)
            
            if process.poll() is None:
                logger.info("隧道启动成功")
                return process
            else:
                stdout, stderr = process.communicate()
                logger.error(f"隧道启动失败: {stderr}")
                return None
                
        except Exception as e:
            logger.error(f"运行隧道时出错: {e}")
            return None
    
    def get_tunnel_url(self, tunnel_id: str) -> Optional[str]:
        """获取隧道 URL"""
        try:
            logger.info(f"获取隧道 {tunnel_id} 的 URL")
            
            # 使用 cloudflared tunnel info 命令
            cmd = f"cloudflared tunnel info {tunnel_id}"
            env = os.environ.copy()
            env['CF_API_TOKEN'] = self.cf_token
            
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, env=env)
            if result.returncode != 0:
                logger.error(f"获取隧道信息失败: {result.stderr}")
                return None
            
            # 从输出中提取 URL
            for line in result.stdout.split('\n'):
                if 'https://' in line and 'trycloudflare.com' in line:
                    url = line.strip().split()[-1]
                    if url.startswith('https://') and 'trycloudflare.com' in url:
                        logger.info(f"隧道 URL: {url}")
                        return url
            
            logger.warning("未找到隧道 URL")
            return None
            
        except Exception as e:
            logger.error(f"获取隧道 URL 时出错: {e}")
            return None
    
    def cleanup_tunnel(self, tunnel_id: str) -> bool:
        """清理隧道"""
        try:
            logger.info(f"清理隧道 {tunnel_id}")
            
            cmd = f"cloudflared tunnel delete -f {tunnel_id}"
            env = os.environ.copy()
            env['CF_API_TOKEN'] = self.cf_token
            
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, env=env)
            if result.returncode != 0:
                logger.error(f"删除隧道失败: {result.stderr}")
                return False
            
            logger.info("隧道删除成功")
            return True
            
        except Exception as e:
            logger.error(f"清理隧道时出错: {e}")
            return False

def main():
    """主函数"""
    try:
        # 获取配置
        cf_token = os.getenv('CF_TOKEN')
        local_port = os.getenv('LOCAL_PORT', '11434')
        local_url = f"http://localhost:{local_port}"
        
        if not cf_token:
            logger.error("CF_TOKEN 环境变量未设置")
            return 1
        
        # 创建管理器
        manager = CloudflareTunnelManager(cf_token)
        
        # 安装 cloudflared
        if not manager.install_cloudflared():
            return 1
        
        # 创建隧道
        tunnel_id = manager.create_tunnel()
        if not tunnel_id:
            return 1
        
        # 配置隧道
        if not manager.configure_tunnel(tunnel_id, local_url):
            manager.cleanup_tunnel(tunnel_id)
            return 1
        
        # 运行隧道
        tunnel_process = manager.run_tunnel()
        if not tunnel_process:
            manager.cleanup_tunnel(tunnel_id)
            return 1
        
        # 获取隧道 URL
        tunnel_url = manager.get_tunnel_url(tunnel_id)
        if tunnel_url:
            logger.info(f"🌐 隧道 URL: {tunnel_url}")
            
            # 保存 URL 到文件供后续使用
            with open('tunnel_url.txt', 'w') as f:
                f.write(tunnel_url)
            
            # 设置 GitHub Actions 输出
            if os.getenv('GITHUB_OUTPUT'):
                with open(os.getenv('GITHUB_OUTPUT'), 'a') as f:
                    f.write(f"tunnel_url={tunnel_url}\n")
        
        logger.info("Cloudflare Tunnel 启动成功，按 Ctrl+C 停止...")
        
        # 等待一段时间让隧道稳定运行
        time.sleep(10)
        
        # 保存隧道进程 ID 以便后续终止
        with open('tunnel_process.pid', 'w') as f:
            f.write(str(tunnel_process.pid))
        
        logger.info("隧道已启动并稳定运行，退出脚本")
        return 0
        
    except Exception as e:
        logger.error(f"运行失败: {e}")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
