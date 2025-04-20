import multiprocessing
import os

# 确保日志目录存在
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

bind = "127.0.0.1:8000"  # 绑定到本地8000端口
workers = multiprocessing.cpu_count() * 2 + 1  # 推荐的worker数量
threads = 2
accesslog = os.path.join(log_dir, "access.log")
errorlog = os.path.join(log_dir, "error.log")
loglevel = "info"
timeout = 120 