from flask import Flask, request, redirect, url_for, render_template, session, send_from_directory, jsonify, Response, make_response
import requests
import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
import polyline
import gpxpy
import gpxpy.gpx
from geopy.distance import geodesic
import asyncio
from ai_services import AIService  # 修正导入方式
import uuid
from werkzeug.utils import secure_filename
import pickle  # 导入pickle模块用于数据序列化
import secrets
import time
import aiohttp

# 加载环境变量
load_dotenv()

WEATHER_API_KEY = os.getenv('VISUAL_CROSSING_API_KEY')

# 用于临时存储GPX和天气数据的字典
temp_data_store = {}

# 数据存储路径
DATA_STORE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data_store')
if not os.path.exists(DATA_STORE_DIR):
    os.makedirs(DATA_STORE_DIR)

# 从文件系统加载之前保存的数据
def load_data_from_file(data_id):
    """从文件系统加载数据"""
    try:
        file_path = os.path.join(DATA_STORE_DIR, f"{data_id}.pkl")
        if os.path.exists(file_path):
            with open(file_path, 'rb') as f:
                return pickle.load(f)
        return None
    except Exception as e:
        print(f"加载数据错误: {str(e)}")
        return None

# 保存数据到文件系统
def save_data_to_file(data_id, data):
    """保存数据到文件系统"""
    try:
        file_path = os.path.join(DATA_STORE_DIR, f"{data_id}.pkl")
        with open(file_path, 'wb') as f:
            pickle.dump(data, f)
        return True
    except Exception as e:
        print(f"保存数据错误: {str(e)}")
        return False

def decode_polyline(encoded_polyline):
    """解码Strava的polyline编码"""
    try:
        return polyline.decode(encoded_polyline)
    except:
        return []

def get_bounds(points):
    """计算坐标点列表的边界框"""
    if not points:
        return ""
    
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    
    min_lat = min(lats)
    max_lat = max(lats)
    min_lon = min(lons)
    max_lon = max(lons)
    
    # 添加一些边距
    padding = 0.01  # 大约1公里
    min_lat -= padding
    max_lat += padding
    min_lon -= padding
    max_lon += padding
    
    return f"{min_lon},{min_lat},{max_lon},{max_lat}"

app = Flask(__name__, static_folder='static')
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))  # 用于session加密

# Strava API配置
CLIENT_ID = int(os.environ.get('STRAVA_CLIENT_ID', 156185))
CLIENT_SECRET = os.environ.get('STRAVA_CLIENT_SECRET', '28ffaf520015a739e50db00b4607fd5fa5c970c3')
REDIRECT_URI = os.environ.get('STRAVA_REDIRECT_URI', 'https://43.139.72.39/callback')

# Strava API端点
AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/api/v3/oauth/token"
ATHLETE_URL = "https://www.strava.com/api/v3/athlete"
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
ACTIVITY_URL = "https://www.strava.com/api/v3/activities/{id}"

# 配置文件上传
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')

# 确保上传目录存在
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# 初始化AI服务
ai_service = AIService()  # 修正初始化方式

# 添加全局CORS处理
@app.after_request
def add_cors_headers(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
    return response

@app.route('/')
def index():
    # 展示欢迎页面，用户需要点击按钮才会跳转到Strava授权
    return render_template('welcome.html')

@app.route('/dashboard')
def dashboard():
    # 检查令牌是否存在
    if 'access_token' not in session:
        return redirect(url_for('authorize'))
    
    # 检查令牌是否过期
    if is_token_expired():
        # 如果过期，尝试刷新令牌
        refreshed = refresh_token()
        if not refreshed:
            return redirect(url_for('authorize'))
    
    # 获取年份参数
    selected_year = request.args.get('year', datetime.now().year, type=int)
    
    # 获取所有年份的活动数据
    activities_by_year = get_activities_by_years()
    
    if not activities_by_year:
        return "获取活动数据失败，请稍后再试"
    
    # 获取用户信息
    athlete_data = get_athlete_data()
    
    # 获取所有可用年份并排序
    available_years = sorted(activities_by_year.keys(), reverse=True)
    
    # 如果没有指定年份或指定的年份没有数据，使用最近的年份
    if not selected_year or selected_year not in available_years:
        selected_year = available_years[0] if available_years else datetime.now().year
    
    # 获取选定年份的数据
    selected_year_data = activities_by_year.get(selected_year, {
        'activities': [],
        'stats': {
            'count': 0,
            'total_distance_km': 0,
            'formatted_total_time': '0小时0分钟'
        }
    })
    
    return render_template('activities.html', 
                          activities=selected_year_data['activities'],
                          stats=selected_year_data['stats'],
                          athlete=athlete_data,
                          years=available_years,
                          selected_year=selected_year)

@app.route('/route')
def route_planner():
    # 检查令牌是否存在
    if 'access_token' not in session:
        return redirect(url_for('index'))
    
    # 检查令牌是否过期
    if is_token_expired():
        # 如果过期，尝试刷新令牌
        refreshed = refresh_token()
        if not refreshed:
            return redirect(url_for('index'))
            
    return render_template('trainPlanner.html')

@app.route('/authorize')
def authorize():
    # 构建授权URL
    params = {
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code',
        'scope': 'read,activity:read_all,profile:read_all',
        'approval_prompt': 'auto'
    }
    
    # 确保使用 HTTPS 协议
    auth_url = f"{AUTH_URL}?client_id={params['client_id']}&redirect_uri={params['redirect_uri'].replace('http://', 'https://')}&response_type={params['response_type']}&scope={params['scope']}&approval_prompt={params['approval_prompt']}"
    return redirect(auth_url)

@app.route('/callback')
def callback():
    # 处理授权回调
    if 'error' in request.args:
        return f"授权失败: {request.args.get('error')}"
    
    # 获取授权码
    code = request.args.get('code')
    
    # 用授权码交换令牌
    token_data = exchange_code_for_token(code)
    
    if not token_data:
        return "获取令牌失败"
    
    # 保存令牌信息到session
    save_token_to_session(token_data)
    
    # 重定向到仪表盘页面
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    # 清除session中的所有数据
    session.clear()
    return redirect(url_for('index'))

def exchange_code_for_token(code):
    """用授权码交换访问令牌和刷新令牌"""
    payload = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'code': code,
        'grant_type': 'authorization_code'
    }
    
    try:
        response = requests.post(TOKEN_URL, data=payload)
        return response.json() if response.status_code == 200 else None
    except Exception as e:
        print(f"交换令牌时出错: {e}")
        return None

def save_token_to_session(token_data):
    """将令牌信息保存到session"""
    session['access_token'] = token_data.get('access_token')
    session['refresh_token'] = token_data.get('refresh_token')
    session['expires_at'] = token_data.get('expires_at')

def is_token_expired():
    """检查访问令牌是否已过期"""
    expires_at = session.get('expires_at')
    if not expires_at:
        return True
    
    # 如果令牌将在1小时内过期，提前刷新
    return datetime.now().timestamp() > expires_at - 3600

def refresh_token():
    """使用刷新令牌获取新的访问令牌"""
    refresh_token_value = session.get('refresh_token')
    if not refresh_token_value:
        return False
    
    payload = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'refresh_token': refresh_token_value,
        'grant_type': 'refresh_token'
    }
    
    try:
        response = requests.post(TOKEN_URL, data=payload)
        if response.status_code == 200:
            token_data = response.json()
            save_token_to_session(token_data)
            return True
        return False
    except Exception as e:
        print(f"刷新令牌时出错: {e}")
        return False

def get_athlete_data():
    """获取用户信息"""
    access_token = session.get('access_token')
    if not access_token:
        return None
    
    headers = {'Authorization': f'Bearer {access_token}'}
    
    try:
        response = requests.get(ATHLETE_URL, headers=headers)
        return response.json() if response.status_code == 200 else None
    except Exception as e:
        print(f"获取用户信息时出错: {e}")
        return None

def get_activities(page=1, per_page=20, year=None):
    """获取活动列表
    
    Args:
        page: 页码
        per_page: 每页数量
        year: 指定年份（可选）
    """
    if 'access_token' not in session:
        return None
    
    # 如果指定了年份，计算该年的起止时间
    if year:
        start_date = f"{year}-01-01T00:00:00Z"
        end_date = f"{year}-12-31T23:59:59Z"
        params = {
            'access_token': session['access_token'],
            'per_page': 200,  # 获取最大数量的活动
            'after': int(datetime.strptime(start_date, "%Y-%m-%dT%H:%M:%SZ").timestamp()),
            'before': int(datetime.strptime(end_date, "%Y-%m-%dT%H:%M:%SZ").timestamp())
        }
    else:
        params = {
            'access_token': session['access_token'],
            'page': page,
            'per_page': per_page
        }
    
    try:
        response = requests.get(ACTIVITIES_URL, params=params)
        response.raise_for_status()
        activities = response.json()
        
        # 处理每个活动的数据
        for activity in activities:
            # 解码路线数据
            if 'map' in activity and 'summary_polyline' in activity['map']:
                activity['decoded_polyline'] = decode_polyline(activity['map']['summary_polyline'])
            else:
                activity['decoded_polyline'] = []
            
            # 格式化时间
            start_date = datetime.strptime(activity['start_date_local'], "%Y-%m-%dT%H:%M:%SZ")
            activity['formatted_date'] = start_date.strftime("%Y-%m-%d %H:%M")
            activity['year'] = start_date.year
            
            # 格式化时长
            elapsed_time = timedelta(seconds=activity['elapsed_time'])
            hours = elapsed_time.seconds // 3600
            minutes = (elapsed_time.seconds % 3600) // 60
            activity['formatted_time'] = f"{hours}小时{minutes}分钟" if hours > 0 else f"{minutes}分钟"
            
            # 计算配速（分钟/公里）
            if activity['distance'] > 0 and activity['moving_time'] > 0:
                pace = (activity['moving_time'] / 60) / (activity['distance'] / 1000)
                pace_minutes = int(pace)
                pace_seconds = int((pace - pace_minutes) * 60)
                activity['pace'] = f"{pace_minutes}'{ pace_seconds:02d}\""
            else:
                activity['pace'] = "N/A"
        
        return activities
    
    except requests.exceptions.RequestException as e:
        print(f"获取活动列表失败: {e}")
        return None

def get_activities_by_years():
    """获取所有年份的活动数据"""
    all_activities = get_activities(per_page=200)  # 获取最近的200个活动
    if not all_activities:
        return {}
    
    # 按年份分组
    activities_by_year = {}
    for activity in all_activities:
        year = activity['year']
        if year not in activities_by_year:
            activities_by_year[year] = {
                'activities': [],
                'stats': {
                    'count': 0,
                    'total_distance': 0,
                    'total_time': 0
                }
            }
        
        activities_by_year[year]['activities'].append(activity)
        activities_by_year[year]['stats']['count'] += 1
        activities_by_year[year]['stats']['total_distance'] += activity['distance']
        activities_by_year[year]['stats']['total_time'] += activity['moving_time']
    
    # 格式化统计数据
    for year_data in activities_by_year.values():
        stats = year_data['stats']
        stats['total_distance_km'] = round(stats['total_distance'] / 1000, 1)
        total_time = timedelta(seconds=stats['total_time'])
        hours = total_time.days * 24 + total_time.seconds // 3600
        minutes = (total_time.seconds % 3600) // 60
        stats['formatted_total_time'] = f"{hours}小时{minutes}分钟"
    
    return activities_by_year

def get_activity_detail(activity_id):
    """获取单个活动的详细信息
    
    Args:
        activity_id: 活动ID
        
    Returns:
        活动详情或None（如果获取失败）
    """
    access_token = session.get('access_token')
    if not access_token:
        return None
    
    headers = {'Authorization': f'Bearer {access_token}'}
    url = ACTIVITY_URL.format(id=activity_id)
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            activity = response.json()
            
            # 处理日期时间格式
            if 'start_date' in activity:
                start_date = datetime.strptime(activity['start_date'], '%Y-%m-%dT%H:%M:%SZ')
                activity['formatted_date'] = start_date.strftime('%Y-%m-%d %H:%M')
            
            # 转换时间（秒）为可读格式
            if 'moving_time' in activity:
                minutes, seconds = divmod(activity['moving_time'], 60)
                hours, minutes = divmod(minutes, 60)
                if hours > 0:
                    activity['formatted_time'] = f"{hours}时{minutes}分{seconds}秒"
                else:
                    activity['formatted_time'] = f"{minutes}分{seconds}秒"
            
            if 'elapsed_time' in activity:
                minutes, seconds = divmod(activity['elapsed_time'], 60)
                hours, minutes = divmod(minutes, 60)
                if hours > 0:
                    activity['formatted_elapsed_time'] = f"{hours}时{minutes}分{seconds}秒"
                else:
                    activity['formatted_elapsed_time'] = f"{minutes}分{seconds}秒"
            
            # 转换距离（米）为千米
            if 'distance' in activity:
                activity['distance_km'] = round(activity['distance'] / 1000, 2)
            
            # 处理配速和速度
            if 'average_speed' in activity:
                if activity.get('type') == 'Run':
                    # 跑步显示配速（分钟/公里）
                    activity['pace'] = f"{(1000 / activity['average_speed'] / 60):.2f} 分钟/公里"
                else:
                    # 其他运动显示速度（公里/小时）
                    activity['speed'] = f"{(activity['average_speed'] * 3.6):.1f} 公里/小时"
            
            if 'max_speed' in activity:
                if activity.get('type') == 'Run':
                    activity['max_pace'] = f"{(1000 / activity['max_speed'] / 60):.2f} 分钟/公里"
                else:
                    activity['max_speed_kmh'] = f"{(activity['max_speed'] * 3.6):.1f} 公里/小时"
            
            return activity
        return None
    except Exception as e:
        print(f"获取活动详情时出错: {e}")
        return None

def get_min_max_values(data):
    """获取数据的最小值和最大值
    
    Args:
        data: 数据列表
        
    Returns:
        [最小值, 最大值]的列表
    """
    valid_data = [x for x in data if x is not None]
    if not valid_data:
        return [0, 0]
    return [min(valid_data), max(valid_data)]

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/gpx_viewer')
def gpx_viewer():
    return render_template('gpx_viewer.html')

@app.route('/upload_gpx', methods=['POST'])
def upload_gpx():
    if 'gpx_file' not in request.files:
        return jsonify({'error': '没有上传文件'}), 400
    
    file = request.files['gpx_file']
    if file.filename == '':
        return jsonify({'error': '没有选择文件'}), 400
    
    if not file.filename.endswith('.gpx'):
        return jsonify({'error': '请上传GPX文件'}), 400
    
    try:
        # 记录GPX文件上传请求
        with open("logs/upload_gpx_debug.log", "a") as log_file:
            log_file.write(f"\n====== GPX文件上传 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ======\n")
            log_file.write(f"文件名: {file.filename}\n")
            log_file.write(f"会话内容: {dict(session)}\n")
        
        # 保存文件到临时目录
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
        file.save(temp_path)
        
        # 读取GPX文件
        with open(temp_path, 'r') as f:
            gpx = gpxpy.parse(f)
        
        # 删除临时文件
        os.remove(temp_path)
        
        # 提取轨迹点
        points = []
        distances = []
        elevations = []
        total_distance = 0
        elevation_gain = 0
        elevation_loss = 0
        last_elevation = None
        
        for track in gpx.tracks:
            for segment in track.segments:
                last_point = None
                for point in segment.points:
                    points.append([point.latitude, point.longitude])
                    elevations.append(point.elevation)
                    
                    if last_point:
                        # 计算距离
                        distance = geodesic(
                            (last_point.latitude, last_point.longitude),
                            (point.latitude, point.longitude)
                        ).kilometers
                        total_distance += distance
                        distances.append(round(total_distance, 2))
                        
                        # 计算爬升和下降
                        if last_elevation is not None:
                            elevation_diff = point.elevation - last_elevation
                            if elevation_diff > 0:
                                elevation_gain += elevation_diff
                            else:
                                elevation_loss += abs(elevation_diff)
                    else:
                        distances.append(0)
                    
                    last_point = point
                    last_elevation = point.elevation
        
        result = {
            'points': points,
            'stats': {
                'distance': total_distance,
                'elevation_gain': elevation_gain,
                'elevation_loss': elevation_loss
            },
            'elevation_data': {
                'distances': distances,
                'elevations': elevations
            }
        }
        
        # 生成唯一ID并存储数据
        data_id = str(uuid.uuid4())
        data = {
            'gpx_data': result,
            'weather_data': [],
            'timestamp': datetime.now().timestamp()
        }
        
        # 同时存储到内存和文件系统
        temp_data_store[data_id] = data
        save_data_to_file(data_id, data)
        
        # 记录生成的数据ID和数据存储情况
        with open("logs/upload_gpx_debug.log", "a") as log_file:
            log_file.write(f"生成的数据ID: {data_id}\n")
            log_file.write(f"数据存储情况: gpx_data已保存, 数据包含 {len(points)} 个轨迹点\n")
            log_file.write(f"temp_data_store中的keys: {list(temp_data_store.keys())}\n")
            log_file.write(f"文件存储路径: {os.path.join(DATA_STORE_DIR, f'{data_id}.pkl')}\n")
        
        # 仅在session中存储数据ID
        session['data_id'] = data_id
        session.modified = True  # 明确标记session已修改，确保保存
        
        # 记录session保存情况
        with open("logs/upload_gpx_debug.log", "a") as log_file:
            log_file.write(f"session中保存的data_id: {session.get('data_id')}\n")
            log_file.write(f"完整session内容: {dict(session)}\n")
        
        # 在返回数据中包含data_id，便于前端存储
        result['data_id'] = data_id
        
        return jsonify(result)
    except Exception as e:
        app.logger.error(f"处理GPX文件时出错: {str(e)}")
        return jsonify({'error': f'处理GPX文件时出错: {str(e)}'}), 400

def get_historical_weather(lat, lon, target_date):
    """
    获取指定位置过去10年同一天的历史天气数据
    """
    base_url = "https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline"
    
    # 构建过去10年的日期列表
    current_year = datetime.now().year
    dates = []
    weather_data = []
    
    for year in range(current_year - 10, current_year):
        historical_date = target_date.replace(year=year)
        if historical_date < datetime.now():  # 只获取过去的日期
            dates.append(historical_date.strftime("%Y-%m-%d"))
    
    # 获取每一年的天气数据
    for date in dates:
        params = {
            'key': WEATHER_API_KEY,
            'unitGroup': 'metric',
            'include': 'current',
            'elements': 'datetime,temp,humidity,precip,windspeed,conditions',
            'contentType': 'json',
        }
        
        url = f"{base_url}/{lat},{lon}/{date}"
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if 'days' in data and len(data['days']) > 0:
                day_data = data['days'][0]
                weather_data.append({
                    'date': date,
                    'temperature': day_data.get('temp'),
                    'humidity': day_data.get('humidity'),
                    'precipitation': day_data.get('precip'),
                    'windspeed': day_data.get('windspeed'),
                    'conditions': day_data.get('conditions')
                })
        except Exception as e:
            print(f"Error fetching weather data for {date}: {str(e)}")
            continue
    
    return weather_data

@app.route('/get_weather_data', methods=['POST'])
def get_weather_data():
    try:
        data = request.get_json()
        lat = data.get('latitude')
        lon = data.get('longitude')
        target_date = datetime.strptime(data.get('date'), '%Y-%m-%d')
        
        historical_weather = get_historical_weather(lat, lon, target_date)
        
        # 检查session中是否有数据ID
        data_id = session.get('data_id')
        if data_id:
            # 先检查内存数据
            if data_id in temp_data_store:
                # 更新内存中的天气数据
                temp_data_store[data_id]['weather_data'] = historical_weather
                # 同时更新文件系统
                save_data_to_file(data_id, temp_data_store[data_id])
                print(f"已更新内存和文件系统中的天气数据: {data_id}")
            else:
                # 尝试从文件系统加载
                stored_data = load_data_from_file(data_id)
                if stored_data:
                    # 更新数据
                    stored_data['weather_data'] = historical_weather
                    # 保存到内存和文件系统
                    temp_data_store[data_id] = stored_data
                    save_data_to_file(data_id, stored_data)
                    print(f"已从文件加载并更新天气数据: {data_id}")
                else:
                    print(f"未找到数据ID来更新天气: {data_id}")
            
            # 记录日志
            with open("logs/weather_data_debug.log", "a") as log_file:
                log_file.write(f"\n====== 更新天气数据 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ======\n")
                log_file.write(f"数据ID: {data_id}\n")
                log_file.write(f"获取到天气数据: {len(historical_weather)} 条记录\n")
                log_file.write(f"内存中是否存在此ID: {data_id in temp_data_store}\n")
                file_path = os.path.join(DATA_STORE_DIR, f"{data_id}.pkl")
                log_file.write(f"文件是否存在: {os.path.exists(file_path)}\n")
        
        return jsonify({
            'status': 'success',
            'data': historical_weather
        })
    except Exception as e:
        print(f"获取天气数据出错: {str(e)}")
        with open("logs/weather_data_debug.log", "a") as log_file:
            log_file.write(f"\n====== 天气数据错误 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ======\n")
            log_file.write(f"错误: {str(e)}\n")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/get_training_advice')
def get_training_advice():
    """
    获取训练建议的流式响应
    """
    try:
        # 添加调试日志
        print("\n====== 训练建议请求 ======")
        print(f"会话内容: {dict(session)}")
        print(f"临时数据存储Keys: {list(temp_data_store.keys())}")
        print(f"请求参数: {request.args}")
        
        # 记录到日志文件
        with open("logs/training_advice_debug.log", "a") as log_file:
            log_file.write("\n====== 训练建议请求 ======\n")
            log_file.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            log_file.write(f"会话内容: {dict(session)}\n")
            log_file.write(f"临时数据存储Keys: {list(temp_data_store.keys())}\n")
            log_file.write(f"数据存储目录文件数: {len(os.listdir(DATA_STORE_DIR))}\n")
            log_file.write(f"请求参数: {request.args}\n")
        
        # 首先尝试从URL参数获取data_id，如果没有再从session获取
        data_id = request.args.get('data_id')
        if not data_id:
            data_id = session.get('data_id')
            
        print(f"使用的data_id: {data_id}")
        with open("logs/training_advice_debug.log", "a") as log_file:
            log_file.write(f"使用的data_id: {data_id}\n")
        
        # 先检查内存中是否有数据
        stored_data = None
        data_source = "未找到"
        
        if data_id in temp_data_store:
            stored_data = temp_data_store[data_id]
            data_source = "内存"
        else:
            # 如果内存中没有，尝试从文件加载
            file_data = load_data_from_file(data_id)
            if file_data:
                # 找到文件数据，同时更新内存
                stored_data = file_data
                temp_data_store[data_id] = file_data  # 更新内存数据
                data_source = "文件"
        
        # 记录数据来源
        with open("logs/training_advice_debug.log", "a") as log_file:
            log_file.write(f"数据来源: {data_source}\n")
        
        if not stored_data:
            print(f"未找到数据ID: {data_id}")
            with open("logs/training_advice_debug.log", "a") as log_file:
                log_file.write(f"未找到数据ID: {data_id}\n")
                log_file.write(f"原因: {'data_id为空' if not data_id else '内存和文件系统中都未找到此data_id'}\n")
                log_file.write(f"内存中的keys: {list(temp_data_store.keys())}\n")
                log_file.write(f"查找的文件路径: {os.path.join(DATA_STORE_DIR, f'{data_id}.pkl')}\n")
                log_file.write(f"该文件是否存在: {os.path.exists(os.path.join(DATA_STORE_DIR, f'{data_id}.pkl'))}\n")
            return jsonify({'error': '未找到GPX数据，请先上传路线'}), 400
        
        # 从请求参数中获取比赛日期
        match_date = request.args.get('match_date')
        if not match_date:
            with open("logs/training_advice_debug.log", "a") as log_file:
                log_file.write("错误: 未提供比赛日期\n")
            return jsonify({'error': '请提供比赛日期'}), 400
        
        # 从存储中获取数据
        gpx_data = stored_data.get('gpx_data')
        weather_data = stored_data.get('weather_data', [])
        
        # 检查是否使用自定义提示词
        use_custom_prompts = request.args.get('custom_prompts', 'false').lower() == 'true'
        custom_system_prompt = session.get('custom_system_prompt', '')
        custom_user_prompt = session.get('custom_user_prompt', '')
        
        # 记录提示词使用情况
        with open("logs/training_advice_debug.log", "a") as log_file:
            log_file.write(f"使用自定义提示词: {use_custom_prompts}\n")
            if use_custom_prompts:
                log_file.write(f"自定义系统提示词长度: {len(custom_system_prompt)}\n")
                log_file.write(f"自定义用户提示词长度: {len(custom_user_prompt)}\n")
        
        # 记录获取到的数据
        with open("logs/training_advice_debug.log", "a") as log_file:
            log_file.write(f"获取到数据: data_id={data_id}, gpx_data存在={gpx_data is not None}, weather_data长度={len(weather_data)}\n")
        
        # 确保数据结构完整
        if not gpx_data or not isinstance(gpx_data, dict) or 'stats' not in gpx_data:
            print("GPX数据结构不完整:", gpx_data)
            with open("logs/training_advice_debug.log", "a") as log_file:
                log_file.write(f"错误: GPX数据结构不完整: {gpx_data}\n")
            return jsonify({'error': 'GPX数据不完整，请重新上传'}), 400
        
        # 创建一个标准生成器函数，包装异步生成器的结果
        def generate():
            # 创建事件循环
            loop = asyncio.new_event_loop()
            
            # 包装异步生成器的协程
            async def fetch_chunks():
                try:
                    # 根据是否使用自定义提示词来调用不同的方法
                    if use_custom_prompts and custom_system_prompt and custom_user_prompt:
                        async for text_chunk in ai_service.generate_training_advice_stream_with_custom_prompts(
                            gpx_data, 
                            weather_data, 
                            match_date, 
                            custom_system_prompt, 
                            custom_user_prompt
                        ):
                            # 确保文本是字符串并转义JSON特殊字符
                            if isinstance(text_chunk, str):
                                yield f"data: {json.dumps({'text': text_chunk})}\n\n"
                    else:
                        async for text_chunk in ai_service.generate_training_advice_stream(gpx_data, weather_data, match_date):
                            # 确保文本是字符串并转义JSON特殊字符
                            if isinstance(text_chunk, str):
                                yield f"data: {json.dumps({'text': text_chunk})}\n\n"
                except Exception as e:
                    error_msg = str(e)
                    print(f"生成训练建议时出错: {error_msg}")
                    yield f"data: {json.dumps({'error': error_msg})}\n\n"
            
            # 创建一个任务用于获取所有chunks
            async def get_all_chunks():
                async for chunk in fetch_chunks():
                    yield chunk
            
            # 运行异步生成器并将结果同步返回
            async_gen = get_all_chunks()
            
            try:
                while True:
                    try:
                        # 让事件循环运行下一个异步迭代
                        chunk = loop.run_until_complete(async_gen.__anext__())
                        yield chunk
                    except StopAsyncIteration:
                        break
            finally:
                loop.close()
        
        return Response(generate(), mimetype='text/event-stream')
    except Exception as e:
        print(f"训练建议路由出错: {str(e)}")
        return jsonify({'error': str(e)}), 500

# 定期清理临时数据
def cleanup_temp_data():
    current_time = datetime.now().timestamp()
    expired_ids = []
    
    with open("logs/cleanup_temp_data.log", "a") as log_file:
        log_file.write(f"\n====== 清理临时数据 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ======\n")
        log_file.write(f"当前数据ID列表: {list(temp_data_store.keys())}\n")
    
    for data_id, data in temp_data_store.items():
        # 数据存储超过24小时则清理（原先是2小时）
        if current_time - data.get('timestamp', 0) > 24 * 60 * 60:
            expired_ids.append(data_id)
    
    for data_id in expired_ids:
        print(f"清理过期数据ID: {data_id}")
        with open("logs/cleanup_temp_data.log", "a") as log_file:
            log_file.write(f"清理过期数据ID: {data_id}, 存储时间: {datetime.fromtimestamp(temp_data_store[data_id].get('timestamp', 0)).strftime('%Y-%m-%d %H:%M:%S')}\n")
        temp_data_store.pop(data_id, None)
    
    with open("logs/cleanup_temp_data.log", "a") as log_file:
        log_file.write(f"清理后的数据ID列表: {list(temp_data_store.keys())}\n")

@app.route('/activity/<int:activity_id>')
def activity_detail(activity_id):
    """活动详情页面
    
    Args:
        activity_id: 活动ID
    """
    # 获取活动详情
    activity = get_activity_detail(activity_id)
    if not activity:
        return "获取活动详情失败", 500
    
    # 获取活动的GPS点数据
    points = []
    start_lat = None
    start_lng = None
    
    if activity.get('map') and activity['map'].get('polyline'):
        points = decode_polyline(activity['map']['polyline'])
        if points:
            start_lat = points[0][0]
            start_lng = points[0][1]
    
    # 获取活动的流数据（心率、配速等）
    streams = get_activity_streams(activity_id)
    
    # 获取分段数据
    segments = get_activity_segments(activity)
    
    return render_template('activity_detail.html',
                         activity=activity,
                         points=points,
                         start_lat=start_lat,
                         start_lng=start_lng,
                         streams=streams,
                         segments=segments)

def get_activity_streams(activity_id):
    """获取活动的流数据
    
    Args:
        activity_id: 活动ID
    """
    if 'access_token' not in session:
        return None
    
    headers = {'Authorization': f'Bearer {session["access_token"]}'}
    url = f"https://www.strava.com/api/v3/activities/{activity_id}/streams"
    params = {
        'keys': 'time,distance,heartrate,cadence,watts,altitude,velocity_smooth,grade_smooth',
        'key_by_type': True
    }
    
    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json()
            streams = {
                'time': data.get('time', {}).get('data', []),
                'distance': data.get('distance', {}).get('data', []),
                'heartrate': data.get('heartrate', {}).get('data', []),
                'cadence': data.get('cadence', {}).get('data', []),
                'watts': data.get('watts', {}).get('data', []),
                'altitude': data.get('altitude', {}).get('data', []),
                'velocity': data.get('velocity_smooth', {}).get('data', []),
                'grade': data.get('grade_smooth', {}).get('data', [])
            }
            
            # 计算配速数据（分钟/公里）
            if streams['velocity']:
                streams['pace'] = [1000 / v / 60 if v > 0 else 0 for v in streams['velocity']]
            else:
                streams['pace'] = []
            
            return streams
        return None
    except Exception as e:
        print(f"获取活动流数据时出错: {e}")
        return None

def get_activity_segments(activity):
    """处理活动分段数据
    
    Args:
        activity: 活动详情数据
    """
    if not activity.get('splits_metric'):
        return None
    
    segments = []
    for split in activity['splits_metric']:
        segment = {
            'distance_km': round(split['distance'] / 1000, 2),
            'elevation_gain': round(split['elevation_difference']),
            'formatted_time': format_duration(split['moving_time'])
        }
        
        # 计算配速或速度
        if activity['type'] == 'Run':
            # 跑步显示配速（分钟/公里）
            pace = split['moving_time'] / 60 / (split['distance'] / 1000)
            pace_minutes = int(pace)
            pace_seconds = int((pace - pace_minutes) * 60)
            segment['pace'] = f"{pace_minutes}:{pace_seconds:02d}"
        else:
            # 其他运动显示速度（公里/小时）
            segment['speed'] = round((split['distance'] / split['moving_time']) * 3.6, 1)
        
        segments.append(segment)
    
    return segments

def format_duration(seconds):
    """格式化时间
    
    Args:
        seconds: 秒数
    """
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"

@app.route('/debug/temp_data_store')
def debug_temp_data_store():
    """调试路由，返回temp_data_store的内容"""
    return {
        'keys': list(temp_data_store.keys()),
        'count': len(temp_data_store),
        'session_data_id': session.get('data_id')
    }

@app.route('/get_default_prompts')
def get_default_prompts():
    """获取默认的系统提示词和用户提示词"""
    try:
        # 添加日志记录请求信息
        print("\n====== 获取默认提示词请求 ======")
        print(f"请求URL: {request.url}")
        print(f"请求方法: {request.method}")
        print(f"请求头: {request.headers}")
        
        with open("logs/prompt_debug.log", "a") as log_file:
            log_file.write("\n====== 获取默认提示词请求 ======\n")
            log_file.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            log_file.write(f"请求URL: {request.url}\n")
            log_file.write(f"请求方法: {request.method}\n")
            log_file.write(f"请求头: {dict(request.headers)}\n")
        
        system_prompt = ai_service.system_prompt
        
        # 构建一个示例用户提示词，不包含具体数据
        user_prompt = """根据以下比赛路线和天气数据，提供详细的训练建议。

## 比赛路线数据:
- 总距离: {total_distance:.2f} 公里;
- 总爬升: {elevation_gain:.0f} 米;
- 总下降: {elevation_loss:.0f} 米;
- 平均坡度: {avg_grade:.1f}%;
- 分段数据：{km_data_text};

## 比赛日当天的天气预报数据:
{weather_summary}

## 当前时间:
{time_now_str}

## 比赛时间:
{match_date}
"""
        
        response = jsonify({
            'status': 'success',
            'system_prompt': system_prompt,
            'user_prompt': user_prompt
        })
        
        # 记录响应信息
        with open("logs/prompt_debug.log", "a") as log_file:
            log_file.write(f"响应状态: 200 OK\n")
            log_file.write(f"响应头: {dict(response.headers)}\n")
        
        return response
    except Exception as e:
        error_msg = str(e)
        print(f"获取默认提示词出错: {error_msg}")
        
        with open("logs/prompt_debug.log", "a") as log_file:
            log_file.write(f"错误: {error_msg}\n")
            import traceback
            log_file.write(f"堆栈跟踪: {traceback.format_exc()}\n")
        
        response = jsonify({
            'status': 'error',
            'message': error_msg
        })
        
        return response, 500

@app.route('/submit_custom_prompts', methods=['POST'])
def submit_custom_prompts():
    """接收用户自定义的提示词"""
    try:
        # 添加日志记录请求信息
        print("\n====== 提交自定义提示词请求 ======")
        print(f"请求URL: {request.url}")
        print(f"请求方法: {request.method}")
        print(f"请求头: {request.headers}")
        
        with open("logs/prompt_debug.log", "a") as log_file:
            log_file.write("\n====== 提交自定义提示词请求 ======\n")
            log_file.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            log_file.write(f"请求URL: {request.url}\n")
            log_file.write(f"请求方法: {request.method}\n")
            log_file.write(f"请求头: {dict(request.headers)}\n")
        
        data = request.get_json()
        system_prompt = data.get('system_prompt', '')
        user_prompt = data.get('user_prompt', '')
        
        # 记录请求参数
        with open("logs/prompt_debug.log", "a") as log_file:
            log_file.write(f"系统提示词长度: {len(system_prompt)}\n")
            log_file.write(f"用户提示词长度: {len(user_prompt)}\n")
        
        # 保存到会话中，以便后续请求使用
        session['custom_system_prompt'] = system_prompt
        session['custom_user_prompt'] = user_prompt
        
        response = jsonify({
            'status': 'success',
            'message': '自定义提示词已保存'
        })
        
        # 记录响应信息
        with open("logs/prompt_debug.log", "a") as log_file:
            log_file.write(f"响应状态: 200 OK\n")
            log_file.write(f"响应头: {dict(response.headers)}\n")
        
        return response
    except Exception as e:
        error_msg = str(e)
        print(f"提交自定义提示词出错: {error_msg}")
        
        with open("logs/prompt_debug.log", "a") as log_file:
            log_file.write(f"错误: {error_msg}\n")
            import traceback
            log_file.write(f"堆栈跟踪: {traceback.format_exc()}\n")
        
        response = jsonify({
            'status': 'error',
            'message': error_msg
        })
        
        return response, 500

# 处理CORS预检请求的路由
@app.route('/get_default_prompts', methods=['OPTIONS'])
def options_default_prompts():
    response = app.make_default_options_response()
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
    return response

@app.route('/submit_custom_prompts', methods=['OPTIONS'])
def options_submit_prompts():
    response = app.make_default_options_response()
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
    return response

if __name__ == '__main__':
    # 确保templates目录存在
    if not os.path.exists('templates'):
        os.makedirs('templates')
    app.run(host='0.0.0.0', port=5000, debug=True) 