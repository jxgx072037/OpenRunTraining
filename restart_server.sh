#!/bin/bash

# 输出时间戳
echo "开始重启服务器 - $(date)"

# 切换到项目目录
cd /home/ubuntu/OpenRunTraining

# 停止当前运行的所有gunicorn进程
echo "停止当前运行的服务器..."
pkill -f gunicorn

# 等待2秒确保进程完全停止
sleep 2

# 激活虚拟环境并启动服务器
echo "启动新的服务器..."
source env/bin/activate && gunicorn -c gunicorn_config.py app:app -D

# 等待2秒让服务器完全启动
sleep 2

# 检查服务器是否成功启动
if pgrep -f gunicorn > /dev/null
then
    echo "服务器重启成功！"
    echo "运行中的gunicorn进程："
    ps aux | grep gunicorn | grep -v grep
else
    echo "服务器启动失败，请检查日志！"
fi

echo "重启操作完成 - $(date)" 