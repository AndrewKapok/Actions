#!/usr/bin/env python3
"""
处理JSON格式的提示词并运行Ollama模型
"""

import os
import sys
import json
import requests
import time
from datetime import datetime
import logging
from typing import List, Dict, Any, Optional

# 创建必要的目录
def create_directories():
    """创建必要的目录"""
    directories = ["logs", "results"]
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        print(f"✅ 创建目录: {directory}")

create_directories()

# 配置日志
def setup_logging():
    """设置日志配置"""
    log_dir = "logs"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = f'{log_dir}/run_prompts_{timestamp}.log'
    
    # 确保日志目录存在
    os.makedirs(log_dir, exist_ok=True)
    
    # 配置日志
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    
    # 避免重复添加处理器
    if not logger.handlers:
        # 文件处理器
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        
        # 控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        
        # 格式器
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
    
    return logger, log_file

logger, log_file = setup_logging()

class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434", max_retries: int = 10):
        self.base_url = base_url
        self.max_retries = max_retries
        self.health_check()
    
    def health_check(self):
        """检查Ollama服务是否就绪"""
        for i in range(self.max_retries):
            try:
                response = requests.get(f"{self.base_url}/api/tags", timeout=10)
                if response.status_code == 200:
                    logger.info(f"✅ Ollama服务已就绪 (尝试 {i+1}/{self.max_retries})")
                    
                    # 检查可用模型
                    models = response.json().get("models", [])
                    if models:
                        model_names = [m.get('name', '未知') for m in models]
                        logger.info(f"📦 可用模型: {', '.join(model_names)}")
                    else:
                        logger.warning("⚠️ 没有找到模型，可能需要拉取模型")
                    return True
            except requests.exceptions.ConnectionError:
                if i < self.max_retries - 1:
                    wait_time = 5 * (i + 1)  # 指数退避
                    logger.warning(f"⏳ 等待Ollama服务启动... ({i+1}/{self.max_retries}) 等待{wait_time}秒")
                    time.sleep(wait_time)
                else:
                    logger.error("❌ Ollama服务启动失败")
                    return False
            except Exception as e:
                logger.error(f"❌ 检查Ollama服务时出错: {e}")
                if i < self.max_retries - 1:
                    time.sleep(5)
        
        logger.error("❌ 无法连接到Ollama服务，请检查服务是否正常运行")
        return False
    
    def list_models(self) -> List[Dict]:
        """列出所有可用模型"""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=10)
            response.raise_for_status()
            return response.json().get("models", [])
        except Exception as e:
            logger.error(f"获取模型列表失败: {e}")
            return []
    
    def generate(self, model: str, prompt: str, temperature: float = 0.7, 
                 max_tokens: int = 1024, **kwargs) -> Dict[str, Any]:
        """生成文本"""
        url = f"{self.base_url}/api/generate"
        
        payload = {
            "model": model,
            "prompt": prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            **kwargs
        }
        
        try:
            logger.debug(f"发送请求到Ollama: model={model}, prompt_length={len(prompt)}")
            
            response = requests.post(url, json=payload, timeout=300)
            response.raise_for_status()
            return response.json()
                
        except requests.exceptions.Timeout:
            logger.error("请求超时，可能需要增加超时时间或检查模型状态")
            raise
        except Exception as e:
            logger.error(f"生成请求失败: {e}")
            raise
    
    def chat(self, model: str, messages: List[Dict], temperature: float = 0.7, 
             max_tokens: int = 1024, **kwargs) -> Dict[str, Any]:
        """聊天模式（如果模型支持）"""
        url = f"{self.base_url}/api/chat"
        
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            **kwargs
        }
        
        try:
            response = requests.post(url, json=payload, timeout=300)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"聊天请求失败: {e}")
            raise

def load_prompts_from_json(json_str: str) -> List[Dict[str, Any]]:
    """从JSON字符串加载提示词"""
    try:
        prompts_data = json.loads(json_str)
        
        # 支持多种JSON格式
        if isinstance(prompts_data, list):
            # 格式1: [{"id": 1, "prompt": "..."}, ...]
            return prompts_data
        elif isinstance(prompts_data, dict) and "prompts" in prompts_data:
            # 格式2: {"prompts": [...], "config": {...}}
            return prompts_data["prompts"]
        elif isinstance(prompts_data, dict) and "prompt" in prompts_data:
            # 格式3: 单个提示词
            return [prompts_data]
        elif isinstance(prompts_data, dict):
            # 格式4: {"prompt_1": "...", "prompt_2": "..."}
            return [
                {"id": key, "prompt": value} 
                for key, value in prompts_data.items() 
                if key.startswith("prompt_")
            ]
        elif isinstance(prompts_data, str):
            # 格式5: 纯字符串
            return [{"id": 1, "prompt": prompts_data}]
        else:
            raise ValueError(f"无法识别的JSON格式: {type(prompts_data)}")
            
    except json.JSONDecodeError as e:
        logger.error(f"JSON解析失败: {e}")
        if json_str:
            logger.error(f"JSON内容预览: {json_str[:500]}...")
        raise
    except Exception as e:
        logger.error(f"加载提示词失败: {e}")
        raise

def save_results(results: List[Dict[str, Any]], output_dir: str = "results"):
    """保存结果到文件"""
    os.makedirs(output_dir, exist_ok=True)
    
    # 生成时间戳
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 保存JSON格式
    json_file = os.path.join(output_dir, f"results_{timestamp}.json")
    try:
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存JSON文件失败: {e}")
        json_file = None
    
    # 保存文本格式
    txt_file = os.path.join(output_dir, f"results_{timestamp}.txt")
    try:
        with open(txt_file, 'w', encoding='utf-8') as f:
            f.write(f"Ollama模型运行结果 - {timestamp}\n")
            f.write("=" * 60 + "\n\n")
            
            for result in results:
                f.write(f"=== 提示词 ID: {result.get('id', 'N/A')} ===\n")
                f.write(f"时间: {result.get('timestamp', 'N/A')}\n")
                f.write(f"模型: {result.get('model', 'N/A')}\n")
                f.write(f"温度: {result.get('temperature', 'N/A')}\n")
                
                # 格式化提示词
                prompt = result.get('prompt', 'N/A')
                if len(prompt) > 200:
                    f.write(f"提示词: {prompt[:200]}...\n")
                else:
                    f.write(f"提示词: {prompt}\n")
                
                # 格式化响应
                response = result.get('response', 'N/A')
                f.write(f"\n响应:\n{response}\n\n")
                
                # 统计信息
                if 'total_duration' in result:
                    f.write(f"生成耗时: {result['total_duration']:.2f}秒\n")
                
                if 'usage_stats' in result:
                    stats = result['usage_stats']
                    f.write(f"令牌统计: {stats}\n")
                
                if 'error' in result:
                    f.write(f"❌ 错误: {result['error']}\n")
                
                f.write("=" * 60 + "\n\n")
    except Exception as e:
        logger.error(f"保存文本文件失败: {e}")
        txt_file = None
    
    # 生成摘要文件
    summary_file = os.path.join(output_dir, f"summary_{timestamp}.md")
    try:
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write(f"# Ollama运行摘要 - {timestamp}\n\n")
            f.write(f"- 总提示词数: {len(results)}\n")
            
            success_count = len([r for r in results if 'error' not in r])
            f.write(f"- 成功处理: {success_count}\n")
            
            if len(results) > 0:
                total_time = sum(r.get('total_duration', 0) for r in results if 'total_duration' in r)
                avg_time = total_time / len(results) if len(results) > 0 else 0
                f.write(f"- 总生成时间: {total_time:.2f}秒\n")
                f.write(f"- 平均生成时间: {avg_time:.2f}秒\n")
            
            f.write("\n## 结果文件\n")
            if json_file:
                f.write(f"- JSON格式: `{json_file}`\n")
            if txt_file:
                f.write(f"- 文本格式: `{txt_file}`\n")
            f.write(f"- 摘要文件: `{summary_file}`\n")
            f.write(f"- 日志文件: `{log_file}`\n")
    except Exception as e:
        logger.error(f"保存摘要文件失败: {e}")
        summary_file = None
    
    if json_file or txt_file or summary_file:
        logger.info(f"📁 结果已保存")
        if json_file:
            logger.info(f"  - JSON格式: {json_file}")
        if txt_file:
            logger.info(f"  - 文本格式: {txt_file}")
        if summary_file:
            logger.info(f"  - 摘要文件: {summary_file}")
    else:
        logger.warning("⚠️ 没有成功保存任何结果文件")
    
    return json_file, txt_file, summary_file

def main():
    """主函数"""
    logger.info("🚀 开始运行 Ollama 提示词处理脚本")
    logger.info(f"📝 日志文件: {log_file}")
    
    # 从环境变量获取配置
    prompts_json = os.getenv("PROMPTS_JSON")
    model_tag = os.getenv("MODEL_TAG", "huihui_ai/deepseek-r1-abliterated:1.5b")
    temperature = float(os.getenv("TEMPERATURE", "0.7"))
    
    if not prompts_json:
        logger.error("❌ 未找到 PROMPTS_JSON 环境变量")
        logger.info("💡 请确保在 GitHub Secrets 中设置了 PROMPTS_JSON")
        logger.info("💡 示例格式: [{\"prompt\": \"你好\", \"id\": 1}]")
        return 1
    
    logger.info("🎯 配置信息:")
    logger.info(f"  - 模型: {model_tag}")
    logger.info(f"  - 温度: {temperature}")
    logger.info(f"  - 提示词: 从JSON中解析")
    
    try:
        # 加载提示词
        prompts = load_prompts_from_json(prompts_json)
        logger.info(f"✅ 成功加载 {len(prompts)} 个提示词")
        
        # 初始化Ollama客户端
        logger.info("🔗 连接Ollama服务...")
        client = OllamaClient(max_retries=15)
        
        # 检查模型是否可用
        models = client.list_models()
        model_names = [m.get("name", "") for m in models]
        
        if model_tag not in model_names:
            logger.warning(f"⚠️ 模型 '{model_tag}' 不在可用模型列表中")
            logger.info(f"📋 可用模型: {', '.join(model_names)}")
            logger.info("🔄 尝试继续运行...")
        
        results = []
        
        # 处理每个提示词
        for i, prompt_data in enumerate(prompts, 1):
            try:
                # 提取提示词内容
                if isinstance(prompt_data, dict):
                    prompt_text = prompt_data.get("prompt", prompt_data.get("content", ""))
                    prompt_id = prompt_data.get("id", i)
                    prompt_config = prompt_data.get("config", {})
                    
                    # 获取其他配置
                    system_prompt = prompt_data.get("system", "")
                    
                else:
                    prompt_text = str(prompt_data)
                    prompt_id = i
                    prompt_config = {}
                    system_prompt = ""
                
                if not prompt_text.strip():
                    logger.warning(f"⚠️ 提示词 {prompt_id} 为空，跳过")
                    continue
                
                logger.info(f"📝 处理提示词 {prompt_id}/{len(prompts)}")
                if len(prompt_text) > 100:
                    logger.debug(f"提示词内容: {prompt_text[:100]}...")
                else:
                    logger.debug(f"提示词内容: {prompt_text}")
                
                # 准备生成参数
                gen_kwargs = {
                    "model": model_tag,
                    "prompt": prompt_text,
                    "temperature": prompt_config.get("temperature", temperature),
                    "max_tokens": prompt_config.get("max_tokens", 1024),
                }
                
                # 开始时间
                start_time = time.time()
                
                # 使用生成模式
                response = client.generate(**gen_kwargs)
                
                # 计算耗时
                duration = time.time() - start_time
                
                # 构建结果
                result = {
                    "id": prompt_id,
                    "timestamp": datetime.now().isoformat(),
                    "model": model_tag,
                    "temperature": prompt_config.get("temperature", temperature),
                    "prompt": prompt_text,
                    "system_prompt": system_prompt if system_prompt else None,
                    "response": response.get("response", ""),
                    "total_duration": response.get("total_duration", duration),
                    "usage_stats": {
                        "prompt_tokens": response.get("prompt_eval_count", 0),
                        "completion_tokens": response.get("eval_count", 0),
                        "total_tokens": response.get("prompt_eval_count", 0) + 
                                       response.get("eval_count", 0)
                    },
                    "config": prompt_config,
                    "success": True
                }
                
                results.append(result)
                
                # 实时输出
                logger.info(f"✅ 提示词 {prompt_id} 完成，耗时: {duration:.2f}秒")
                if response.get("response"):
                    response_preview = response["response"][:150].replace("\n", " ")
                    logger.info(f"📄 响应预览: {response_preview}...")
                
                # 添加延迟以避免服务器过载
                delay = prompt_config.get("delay", 1)
                if delay > 0:
                    time.sleep(delay)
                
            except Exception as e:
                logger.error(f"❌ 处理提示词 {prompt_id} 时出错: {e}")
                results.append({
                    "id": prompt_id,
                    "timestamp": datetime.now().isoformat(),
                    "model": model_tag,
                    "prompt": prompt_text if 'prompt_text' in locals() else str(prompt_data),
                    "error": str(e),
                    "success": False,
                    "status": "failed"
                })
        
        # 保存结果
        if results:
            json_file, txt_file, summary_file = save_results(results)
            
            success_count = len([r for r in results if r.get("success", False)])
            total_count = len(results)
            
            logger.info(f"🎉 运行完成!")
            logger.info(f"📊 统计: {success_count}/{total_count} 个提示词成功处理")
            
            if success_count < total_count:
                logger.warning(f"⚠️ 有 {total_count - success_count} 个提示词处理失败")
            
        else:
            logger.warning("⚠️ 没有成功处理的提示词")
            
    except Exception as e:
        logger.error(f"❌ 运行失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 1
    
    return 0

if __name__ == "__main__":
    exit_code = main()
    if exit_code == 0:
        logger.info("👋 脚本执行完毕")
    else:
        logger.error(f"❌ 脚本执行失败，退出码: {exit_code}")
    sys.exit(exit_code)
