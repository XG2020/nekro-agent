from typing import AsyncGenerator, Dict, List, Optional, Union
import httpx
import json

from nekro_agent.core.config import config, ModelConfigGroup
from nekro_agent.core.logger import logger
from nekro_agent.libs.miose_llm.clients.chat_openai import (
    gen_openai_chat_response,
    set_openai_base_url,
)


def get_model_config(model_group: str = "") -> Optional[ModelConfigGroup]:
    """获取模型配置

    Args:
        model_group (str, optional): 模型组名称. Defaults to "".

    Returns:
        Optional[ModelConfigGroup]: 模型配置
    """
    if not model_group:
        model_group = config.USE_MODEL_GROUP
    return config.MODEL_GROUPS.get(model_group)


async def get_chat_response(messages: List[Dict[str, str]], model_group: str = "") -> str:
    model_group = model_group or config.USE_MODEL_GROUP
    if model_group not in config.MODEL_GROUPS:
        logger.error(f"指定的模型组 {model_group} 不存在，请检查配置文件")
        raise ValueError(f"指定的模型组 {model_group} 不存在，请检查配置文件")

    for _i in range(3):
        try:
            set_openai_base_url(config.MODEL_GROUPS[model_group].BASE_URL)
            ret, tokens = await gen_openai_chat_response(
                messages=messages,
                model=config.MODEL_GROUPS[model_group].CHAT_MODEL,
                api_key=config.MODEL_GROUPS[model_group].API_KEY,
            )
        except Exception as e:
            logger.error(f"Error while generating chat response: {e}")
        else:
            return ret

    raise Exception("Failed to generate chat response after 3 attempts")


async def get_chat_response_stream(
    messages: List[Dict[str, str]],
    model_group: str = "",
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    top_k: Optional[int] = None,
    presence_penalty: Optional[float] = None,
    frequency_penalty: Optional[float] = None,
    extra_body: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """流式调用 OpenAI 格式的 API 获取聊天回复

    Args:
        messages (List[Dict[str, str]]): 消息列表
        model_group (str, optional): 模型组名称. Defaults to "".
        temperature (Optional[float], optional): 温度. Defaults to None.
        top_p (Optional[float], optional): Top P. Defaults to None.
        top_k (Optional[int], optional): Top K. Defaults to None.
        presence_penalty (Optional[float], optional): 存在惩罚. Defaults to None.
        frequency_penalty (Optional[float], optional): 频率惩罚. Defaults to None.
        extra_body (Optional[str], optional): 额外请求体. Defaults to None.

    Yields:
        str: 生成的文本片段
    """
    model_config = get_model_config(model_group)
    if not model_config:
        raise ValueError(f"未找到模型组配置: {model_group}")

    # 构建请求体
    body = {
        "model": model_config.CHAT_MODEL,
        "messages": messages,
        "stream": True,  # 启用流式响应
    }

    # 添加可选参数
    if temperature is not None or model_config.TEMPERATURE is not None:
        body["temperature"] = temperature or model_config.TEMPERATURE
    if top_p is not None or model_config.TOP_P is not None:
        body["top_p"] = top_p or model_config.TOP_P
    if top_k is not None or model_config.TOP_K is not None:
        body["top_k"] = top_k or model_config.TOP_K
    if presence_penalty is not None or model_config.PRESENCE_PENALTY is not None:
        body["presence_penalty"] = presence_penalty or model_config.PRESENCE_PENALTY
    if frequency_penalty is not None or model_config.FREQUENCY_PENALTY is not None:
        body["frequency_penalty"] = frequency_penalty or model_config.FREQUENCY_PENALTY

    # 添加额外请求体
    if extra_body or model_config.EXTRA_BODY:
        try:
            extra = json.loads(extra_body or model_config.EXTRA_BODY or "{}")
            body.update(extra)
        except Exception as e:
            logger.error(f"解析额外请求体失败: {e}")

    # 设置代理
    proxies = {}
    if model_config.CHAT_PROXY:
        proxies["http://"] = model_config.CHAT_PROXY
        proxies["https://"] = model_config.CHAT_PROXY
    elif config.DEFAULT_PROXY:
        proxies["http://"] = config.DEFAULT_PROXY
        proxies["https://"] = config.DEFAULT_PROXY

    headers = {"Authorization": f"Bearer {model_config.API_KEY}"}

    try:
        async with httpx.AsyncClient(proxies=proxies) as client:
            async with client.stream(
                "POST",
                f"{model_config.BASE_URL}/chat/completions",
                json=body,
                headers=headers,
                timeout=60,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.strip():
                        if line.startswith("data: "):
                            line = line[6:]  # 移除 "data: " 前缀
                        if line == "[DONE]":
                            break
                        try:
                            chunk = json.loads(line)
                            if chunk.get("choices") and chunk["choices"][0].get("delta", {}).get("content"):
                                yield chunk["choices"][0]["delta"]["content"]
                        except json.JSONDecodeError:
                            continue
    except Exception as e:
        logger.error(f"调用 LLM API 失败: {e}")
        raise
