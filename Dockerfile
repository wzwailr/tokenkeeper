FROM python:3.11-slim

WORKDIR /app

# 只安装看板依赖
RUN pip install --no-cache-dir tokenkeeper-ai[dashboard]

# 暴露 Streamlit 默认端口
EXPOSE 8501

# 健康检查
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501')"

# 默认命令：启动看板，DB 路径通过环境变量传入
ENTRYPOINT ["tokenkeeper", "dashboard"]
