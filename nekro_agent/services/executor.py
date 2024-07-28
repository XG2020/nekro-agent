import asyncio
import os
from pathlib import Path

import aiodocker
import aiohttp
from aiodocker.docker import DockerContainer

from nekro_agent.core.config import config
from nekro_agent.core.logger import logger

HOST_DIR = Path(config.SANDBOX_SHARED_HOST_DIR).resolve()  # 主机共享目录
USER_UPLOAD_DIR = Path(config.USER_UPLOAD_DIR).resolve()  # 用户上传目录

IMAGE_NAME = "nekro-agent-sandbox"  # Docker 镜像名称
CONTAINER_SHARE_DIR = "/app/shared"  # 容器内共享目录 (读写)
CONTAINER_UPLOAD_DIR = "/app/uploads"  # 容器上传目录 (只读)
CONTAINER_WORK_DIR = "/app"  # 容器工作目录

CODE_FILENAME = "run_script.py.code"  # 要执行的代码文件名
RUN_CODE_FILENAME = "run_script.py"  # 要执行的代码文件名

CODE_RUN_ERROR_FLAG = "[CODE_RUN_ERROR]"  # 代码运行错误标记

EXEC_SCRIPT = f"""
cp {CONTAINER_SHARE_DIR}/{CODE_FILENAME} {CONTAINER_WORK_DIR}/{RUN_CODE_FILENAME} &&
python {RUN_CODE_FILENAME}
if [ $? -ne 0 ]; then
    echo "{CODE_RUN_ERROR_FLAG}"
fi
"""

CODE_PREAMBLE = """
import requests
CHAT_API = "http://host.docker.internal:8001/api"
"""

# 设置共享目录权限
try:
    Path.chmod(HOST_DIR, 0o777)
    logger.info(f"设置共享目录权限: {HOST_DIR} 777")
except Exception as e:
    logger.error(f"设置共享目录权限失败: {e}")


# 沙盒并发限制
semaphore = asyncio.Semaphore(config.SANDBOX_MAX_CONCURRENT)


async def limited_run_code(code_text: str, output_limit: int = 1000) -> str:
    """限制并发运行代码"""

    async with semaphore:
        return await run_code_in_sandbox(code_text, output_limit)


async def run_code_in_sandbox(code_text: str, output_limit: int = 1000) -> str:
    """在沙盒容器中运行代码并获取输出"""

    Path(HOST_DIR).mkdir(parents=True, exist_ok=True)
    code_file_path = Path(HOST_DIR) / CODE_FILENAME
    Path.write_text(code_file_path, f"{CODE_PREAMBLE.strip()}\n\n{code_text}")

    # 启动容器
    docker = aiodocker.Docker()
    container_name = f"nekro-agent-sandbox-{os.urandom(4).hex()}"
    container: DockerContainer = await docker.containers.run(
        name=container_name,
        config={
            "Image": IMAGE_NAME,
            "Cmd": ["bash", "-c", EXEC_SCRIPT],
            "HostConfig": {
                "Binds": [
                    f"{HOST_DIR}:{CONTAINER_SHARE_DIR}:rw",
                    f"{USER_UPLOAD_DIR}:{CONTAINER_UPLOAD_DIR}:ro",
                ],
                "Memory": 512 * 1024 * 1024,  # 内存限制 (512MB)
                "NanoCPUs": 1000000000,  # CPU 限制 (1 core)
                "SecurityOpt": [
                    "no-new-privileges",  # 禁止提升权限
                    "apparmor=unconfined",  # 可以根据需要设置 AppArmor 配置
                ],
                "NetworkMode": "bridge",
                "ExtraHosts": ["host.docker.internal:host-gateway"],
            },
            "User": "nobody",  # 非特权用户
            "AutoRemove": True,
        },
    )
    logger.info(f"启动容器: {container_name} | ID: {container.id}")

    # 等待容器执行并限制时间
    output_text = await run_container_with_timeout(
        container,
        config.SANDBOX_RUNNING_TIMEOUT,
    )
    return (
        output_text
        if len(output_text) <= output_limit
        else f"(output too long, hidden {len(output_text) - output_limit} characters)...{output_text[-output_limit:]}"
    )


async def run_container_with_timeout(container: DockerContainer, timeout: int) -> str:
    try:
        task = asyncio.create_task(asyncio.wait_for(container.wait(), timeout=timeout))
        await asyncio.wait_for(task, timeout=timeout)
        outputs = await container.log(stdout=True, stderr=True)
        await container.delete()
        logger.info(f"容器 {container.id} 运行结束退出")
    except asyncio.TimeoutError:
        logger.warning(f"容器 {container.id} 运行超过 {timeout} 秒，强制停止容器")
        outputs = await container.log(stdout=True, stderr=True)
        outputs.append(f"# This container has been killed because it exceeded the {timeout} seconds limit.")
        await container.kill()
        await container.delete()

    # 获取容器输出
    return "".join(outputs).strip()


async def cleanup_sandbox_containers():
    docker = aiodocker.Docker()
    try:
        containers = await docker.containers.list(all=True)
        for container in containers:
            container_info = await container.show()
            if IMAGE_NAME in container_info["Name"]:
                await container.kill()
                await container.delete()
                logger.info(f"已清理容器 {container_info['Name']}")
    finally:
        await docker.close()
