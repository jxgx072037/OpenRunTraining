#!/bin/bash
# OpenRunTraining 常用部署命令

# 重启服务
restart_services() {
    echo "正在重启 Gunicorn 服务..."
    sudo systemctl restart openrun
    echo "正在重启 Nginx 服务..."
    sudo systemctl restart nginx
    echo "服务已重启!"
}

# 查看日志
view_logs() {
    echo "Gunicorn 访问日志 (按q退出):"
    less -S $HOME/OpenRunTraining/logs/access.log
    echo "Gunicorn 错误日志 (按q退出):"
    less -S $HOME/OpenRunTraining/logs/error.log
    echo "Nginx 访问日志 (按q退出):"
    sudo less -S /var/log/nginx/openrun_access.log
    echo "Nginx 错误日志 (按q退出):"
    sudo less -S /var/log/nginx/openrun_error.log
}

# 查看服务状态
check_status() {
    echo "Gunicorn 服务状态:"
    sudo systemctl status openrun
    echo "Nginx 服务状态:"
    sudo systemctl status nginx
}

# 刷新SSL证书
renew_ssl() {
    echo "正在刷新SSL证书..."
    sudo certbot renew
    echo "SSL证书已刷新!"
}

# 显示帮助信息
show_help() {
    echo "OpenRunTraining 部署管理脚本"
    echo "用法: $0 [选项]"
    echo "选项:"
    echo "  restart    重启所有服务"
    echo "  logs       查看所有日志"
    echo "  status     查看服务状态"
    echo "  ssl        刷新SSL证书"
    echo "  help       显示此帮助信息"
}

# 根据命令行参数调用相应的函数
case "$1" in
    restart)
        restart_services
        ;;
    logs)
        view_logs
        ;;
    status)
        check_status
        ;;
    ssl)
        renew_ssl
        ;;
    help|*)
        show_help
        ;;
esac 