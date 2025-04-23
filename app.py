from flask import Flask, request, redirect, url_for, render_template, session, send_from_directory, jsonify, Response
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
from ai_services import ai_service
import uuid

# 加载环境变量
load_dotenv()

WEATHER_API_KEY = os.getenv('VISUAL_CROSSING_API_KEY')

# 用于临时存储GPX和天气数据的字典
temp_data_store = {}

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

@app.route('/')
def index():
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
        return redirect(url_for('authorize'))
    
    # 检查令牌是否过期
    if is_token_expired():
        # 如果过期，尝试刷新令牌
        refreshed = refresh_token()
        if not refreshed:
            return redirect(url_for('authorize'))
            
    return render_template('index.html')

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
    
    # 重定向到首页
    return redirect(url_for('index'))

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
        # 读取GPX文件
        gpx = gpxpy.parse(file)
        
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
        temp_data_store[data_id] = {
            'gpx_data': result,
            'weather_data': [],
            'timestamp': datetime.now().timestamp()
        }
        
        # 仅在session中存储数据ID，而不是整个数据
        session['data_id'] = data_id
        
        return jsonify(result)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 400

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
        if data_id and data_id in temp_data_store:
            # 更新存储的天气数据
            temp_data_store[data_id]['weather_data'] = historical_weather
        
        return jsonify({
            'status': 'success',
            'data': historical_weather
        })
    except Exception as e:
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
        # 从session获取数据ID
        data_id = session.get('data_id')
        if not data_id or data_id not in temp_data_store:
            print(f"未找到数据ID: {data_id}")
            return jsonify({'error': '未找到GPX数据，请先上传路线'}), 400
        
        # 从请求参数中获取比赛日期
        match_date = request.args.get('match_date')
        if not match_date:
            return jsonify({'error': '请提供比赛日期'}), 400
        
        # 从存储中获取数据
        stored_data = temp_data_store[data_id]
        gpx_data = stored_data.get('gpx_data')
        weather_data = stored_data.get('weather_data', [])
        
        # 确保数据结构完整
        if not gpx_data or not isinstance(gpx_data, dict) or 'stats' not in gpx_data:
            print("GPX数据结构不完整:", gpx_data)
            return jsonify({'error': 'GPX数据不完整，请重新上传'}), 400
        
        # 创建一个标准生成器函数，包装异步生成器的结果
        def generate():
            # 创建事件循环
            loop = asyncio.new_event_loop()
            
            # 包装异步生成器的协程
            async def fetch_chunks():
                try:
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
    
    for data_id, data in temp_data_store.items():
        # 数据存储超过30分钟则清理
        if current_time - data.get('timestamp', 0) > 30 * 60:
            expired_ids.append(data_id)
    
    for data_id in expired_ids:
        temp_data_store.pop(data_id, None)
        
# 添加定时器来定期清理数据（可以使用apscheduler等库实现）

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

if __name__ == '__main__':
    # 确保templates目录存在
    if not os.path.exists('templates'):
        os.makedirs('templates')
    app.run(host='0.0.0.0', port=5000, debug=True) 