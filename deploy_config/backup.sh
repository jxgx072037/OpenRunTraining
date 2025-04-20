#!/bin/bash
# OpenRunTraining 备份脚本

# 配置
BACKUP_DIR="$HOME/backups"
APP_DIR="$HOME/OpenRunTraining"
DATE_FORMAT=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="$BACKUP_DIR/openrun_backup_$DATE_FORMAT.tar.gz"

# 创建备份目录
mkdir -p $BACKUP_DIR

echo "开始备份 OpenRunTraining 应用..."

# 备份应用文件
echo "备份代码和配置文件..."
tar -czf $BACKUP_FILE \
    $APP_DIR/app.py \
    $APP_DIR/requirements.txt \
    $APP_DIR/.env \
    $APP_DIR/gunicorn_config.py \
    $APP_DIR/logs \
    $APP_DIR/static \
    $APP_DIR/templates \
    $APP_DIR/deploy_config

# 备份Nginx配置
echo "备份Nginx配置..."
sudo cp /etc/nginx/sites-available/openrun_domains.conf $BACKUP_DIR/openrun_domains.conf.bak

# 备份SSL证书
echo "备份SSL证书..."
sudo cp -r /etc/letsencrypt $BACKUP_DIR/letsencrypt.bak

echo "备份完成!"
echo "备份文件保存在: $BACKUP_FILE"
echo "Nginx配置备份: $BACKUP_DIR/openrun_domains.conf.bak"
echo "SSL证书备份: $BACKUP_DIR/letsencrypt.bak" 