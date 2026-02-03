#!/usr/bin/env python3
"""
处理JSON格式的提示词并运行Ollama模型
"""

import os
import json
import requests
import time
from datetime import datetime
import logging
from typing import List, Dict, Any

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/run_prompts.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        self.health_check()
    
    def health_check(self, max_retries: int = 5, delay: int = 5):
        """检查Ollama服务是否就绪"""
        for i in range(max_retries):
            try:
                response = requests.get(f"{self.base_url}/api/tags")
                if response.status_code == 200:
                    logger.info("Ollama服务已就绪")
                    return True
            except requests.exceptions.ConnectionError:
                logger.warning(f"等待Ollama服务启动... ({i+1}/{max_retries})")
                time.sleep(delay)
        
        raise ConnectionError("无法连接到Ollama服务")
    
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
            response = requests.post(url, json=payload, timeout=300)  # 5分钟超时
            response.raise_for_status()
            return response.json()
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
        else:
            raise ValueError("无法识别的JSON格式")
            
    except json.JSONDecodeError as e:
        logger.error(f"JSON解析失败: {e}")
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
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    # 保存文本格式
    txt_file = os.path.join(output_dir, f"results_{timestamp}.txt")
    with open(txt_file, 'w', encoding='utf-8') as f:
        for result in results:
            f.write(f"=== 提示词 {result.get('id', 'N/A')} ===\n")
            f.write(f"时间: {result.get('timestamp', 'N/A')}\n")
            f.write(f"模型: {result.get('model', 'N/A')}\n")
            f.write(f"温度: {result.get('temperature', 'N/A')}\n")
            f.write(f"提示词:\n{result.get('prompt', 'N/A')}\n\n")
            f.write(f"响应:\n{result.get('response', 'N/A')}\n")
            f.write(f"生成耗时: {result.get('total_duration', 'N/A'):.2f}秒\n")
            f.write(f"令牌统计: {result.get('usage_stats', {})}\n")
            f.write("=" * 50 + "\n\n")
    
    logger.info(f"结果已保存到: {json_file}, {txt_file}")
    return json_file, txt_file

def main():
    # 确保日志目录存在
    os.makedirs("logs", exist_ok=True)
    
    # 从环境变量获取配置
    prompts_json = os.getenv("PROMPTS_JSON")
    model_tag = os.getenv("MODEL_TAG", "huihui_ai/deepseek-r1-abliterated:1.5b")
    temperature = float(os.getenv("TEMPERATURE", "0.7"))
    
    if not prompts_json:
        logger.error("未找到PROMPTS_JSON环境变量")
        return
    
    logger.info(f"开始处理提示词，模型: {model_tag}, 温度: {temperature}")
    
    try:
        # 加载提示词
        prompts = load_prompts_from_json(prompts_json)
        logger.info(f"成功加载 {len(prompts)} 个提示词")
        
        # 初始化Ollama客户端
        client = OllamaClient()
        
        results = []
        
        # 处理每个提示词
        for i, prompt_data in enumerate(prompts, 1):
            try:
                # 提取提示词内容
                if isinstance(prompt_data, dict):
                    prompt_text = prompt_data.get("prompt", prompt_data.get("content", ""))
                    prompt_id = prompt_data.get("id", i)
                    prompt_config = prompt_data.get("config", {})
                else:
                    prompt_text = str(prompt_data)
                    prompt_id = i
                    prompt_config = {}
                
                if not prompt_text.strip():
                    logger.warning(f"提示词 {prompt_id} 为空，跳过")
                    continue
                
                logger.info(f"处理提示词 {prompt_id}: {prompt_text[:100]}...")
                
                # 开始时间
                start_time = time.time()
                
                # 生成响应
                response = client.generate(
                    model=model_tag,
                    prompt=prompt_text,
                    temperature=prompt_config.get("temperature", temperature),
                    max_tokens=prompt_config.get("max_tokens", 1024),
                    **{k: v for k, v in prompt_config.items() 
                       if k not in ["prompt", "id", "temperature", "max_tokens"]}
                )
                
                # 计算耗时
                duration = time.time() - start_time
                
                # 构建结果
                result = {
                    "id": prompt_id,
                    "timestamp": datetime.now().isoformat(),
                    "model": model_tag,
                    "temperature": prompt_config.get("temperature", temperature),
                    "prompt": prompt_text,
                    "response": response.get("response", ""),
                    "total_duration": response.get("total_duration", duration),
                    "usage_stats": {
                        "prompt_tokens": response.get("prompt_eval_count", 0),
                        "completion_tokens": response.get("eval_count", 0),
                        "total_tokens": response.get("prompt_eval_count", 0) + 
                                       response.get("eval_count", 0)
                    },
                    "raw_response": response
                }
                
                results.append(result)
                
                # 实时输出
                logger.info(f"提示词 {prompt_id} 完成，耗时: {duration:.2f}秒")
                logger.info(f"响应: {response.get('response', '')[:200]}...")
                
                # 添加延迟以避免服务器过载
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"处理提示词 {prompt_id} 时出错: {e}")
                results.append({
                    "id": prompt_id,
                    "timestamp": datetime.now().isoformat(),
                    "model": model_tag,
                    "prompt": prompt_text if 'prompt_text' in locals() else str(prompt_data),
                    "error": str(e),
                    "status": "failed"
                })
        
        # 保存结果
        if results:
            save_results(results)
            logger.info(f"成功处理 {len([r for r in results if 'error' not in r])}/{len(prompts)} 个提示词")
        else:
            logger.warning("没有成功处理的提示词")
            
    except Exception as e:
        logger.error(f"运行失败: {e}")
        raise

if __name__ == "__main__":
    main()