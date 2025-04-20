from flask import Flask, request, redirect, url_for, render_template, session, send_from_directory, jsonify
import requests
import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
import polyline
import gpxpy
import gpxpy.gpx
from geopy.distance import geodesic

# 加载环境变量
load_dotenv()

WEATHER_API_KEY = os.getenv('VISUAL_CROSSING_API_KEY')

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
REDIRECT_URI = os.environ.get('STRAVA_REDIRECT_URI', 'http://43.139.72.39/callback')

# Strava API端点
AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/api/v3/oauth/token"
ATHLETE_URL = "https://www.strava.com/api/v3/athlete"
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
ACTIVITY_URL = "https://www.strava.com/api/v3/activities/{id}"

@app.route('/')
def index():
    # 检查令牌是否过期
    if 'access_token' in session and is_token_expired():
        # 如果过期，尝试刷新令牌
        refresh_token()
        
    return render_template('index.html', session=session)

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
    
    auth_url = f"{AUTH_URL}?client_id={params['client_id']}&redirect_uri={params['redirect_uri']}&response_type={params['response_type']}&scope={params['scope']}&approval_prompt={params['approval_prompt']}"
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
    
    # 获取用户信息
    athlete_data = get_athlete_data()
    
    return render_template('profile.html', athlete=athlete_data)

@app.route('/profile')
def profile():
    # 检查令牌是否存在
    if 'access_token' not in session:
        return redirect(url_for('authorize'))
    
    # 检查令牌是否过期
    if is_token_expired():
        # 如果过期，尝试刷新令牌
        refreshed = refresh_token()
        if not refreshed:
            return redirect(url_for('authorize'))
    
    # 获取用户信息
    athlete_data = get_athlete_data()
    
    if not athlete_data:
        return redirect(url_for('authorize'))
    
    return render_template('profile.html', athlete=athlete_data)

@app.route('/activities')
def activities():
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

def filter_pace_outliers(pace_data, multiplier=2.5):
    """使用IQR方法过滤异常的配速数据
    
    Args:
        pace_data: 配速数据列表
        multiplier: IQR乘数，用于调整过滤的严格程度
    
    Returns:
        过滤后的配速数据列表
    """
    # 移除None值和0值
    valid_data = [x for x in pace_data if x is not None and x > 0]
    if not valid_data:
        return pace_data
    
    # 计算四分位数
    valid_data.sort()
    n = len(valid_data)
    q1_idx = int(n * 0.25)
    q3_idx = int(n * 0.75)
    q1 = valid_data[q1_idx]
    q3 = valid_data[q3_idx]
    
    # 计算四分位距
    iqr = q3 - q1
    
    # 设置上下限
    lower_bound = max(2.0, q1 - multiplier * iqr)  # 不允许配速低于2分钟/公里
    upper_bound = min(20.0, q3 + multiplier * iqr)  # 不允许配速高于20分钟/公里
    
    # 过滤数据
    filtered_data = []
    for pace in pace_data:
        if pace is None or pace < lower_bound or pace > upper_bound:
            filtered_data.append(None)
        else:
            filtered_data.append(pace)
    
    return filtered_data

def moving_average(data, window_size=80):
    """计算移动平均
    
    Args:
        data: 数据列表
        window_size: 窗口大小，默认80
        
    Returns:
        移动平均后的数据列表
    """
    if not data or len(data) == 0:
        return []
        
    result = []
    window = min(window_size, len(data))
    
    for i in range(len(data)):
        sum_val = 0
        count = 0
        
        for j in range(max(0, i - window//2), min(len(data), i + window//2 + 1)):
            if data[j] is not None:
                sum_val += data[j]
                count += 1
        
        result.append(sum_val / count if count > 0 else None)
    
    return result

@app.route('/activity/<activity_id>')
def activity_detail(activity_id):
    if 'access_token' not in session:
        return redirect(url_for('login'))

    headers = {'Authorization': f"Bearer {session['access_token']}"}
    
    # 获取活动详情
    response = requests.get(f'https://www.strava.com/api/v3/activities/{activity_id}', headers=headers)
    if response.status_code != 200:
        return "无法获取活动详情"
    
    activity = response.json()
    
    # 获取活动流数据
    streams_response = requests.get(
        f'https://www.strava.com/api/v3/activities/{activity_id}/streams',
        headers=headers,
        params={
            'keys': 'time,distance,heartrate,cadence,altitude,velocity_smooth',
            'key_by_type': True
        }
    )
    
    streams = {}
    if streams_response.status_code == 200:
        streams = streams_response.json()
        
        # 处理流数据
        if streams:
            # 确保所有数据长度一致
            data_length = len(next(iter(streams.values()))['data'])
            stream_data = {
                'distance': [],
                'pace': [],
                'heartrate': [],
                'cadence': [],
                'altitude': [],
                'time': []  # 添加时间数据
            }
            
            # 处理距离数据（转换为千米）
            if 'distance' in streams:
                stream_data['distance'] = [d/1000 for d in streams['distance']['data']]
            
            # 处理时间数据（转换为时:分:秒格式）
            if 'time' in streams:
                stream_data['time'] = []
                for t in streams['time']['data']:
                    hours = t // 3600
                    minutes = (t % 3600) // 60
                    seconds = t % 60
                    if hours > 0:
                        stream_data['time'].append(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
                    else:
                        stream_data['time'].append(f"{minutes:02d}:{seconds:02d}")
            
            # 处理速度数据（转换为配速：分钟/公里）
            if 'velocity_smooth' in streams:
                raw_pace = [round(1000/v/60, 2) if v > 0.1 else None for v in streams['velocity_smooth']['data']]
                stream_data['pace'] = moving_average(raw_pace)
            
            # 处理心率数据
            if 'heartrate' in streams:
                stream_data['heartrate'] = moving_average(streams['heartrate']['data'])
            
            # 处理步频数据（乘以2，因为API返回的是单脚步频）
            if 'cadence' in streams:
                raw_cadence = [c * 2 if c is not None else None for c in streams['cadence']['data']]
                stream_data['cadence'] = moving_average(raw_cadence)
            
            # 处理海拔数据
            if 'altitude' in streams:
                stream_data['altitude'] = streams['altitude']['data']
            
            # 计算各指标的最大最小值
            stream_data['pace_range'] = get_min_max_values(stream_data['pace'])
            stream_data['heartrate_range'] = get_min_max_values(stream_data['heartrate'])
            stream_data['cadence_range'] = get_min_max_values(stream_data['cadence'])
            stream_data['altitude_range'] = get_min_max_values(stream_data['altitude'])
    
    # 获取分段数据
    segments_response = requests.get(f'https://www.strava.com/api/v3/activities/{activity_id}/laps', headers=headers)
    segments = []
    if segments_response.status_code == 200:
        segments = segments_response.json()
        for segment in segments:
            # 计算配速（分钟/公里）或速度（公里/小时）
            if segment.get('average_speed'):
                if activity.get('type') == 'Run':
                    segment['pace'] = round(1000 / segment['average_speed'] / 60, 2)
                else:
                    segment['speed'] = round(segment['average_speed'] * 3.6, 1)
            
            # 转换距离为千米
            if 'distance' in segment:
                segment['distance_km'] = round(segment['distance'] / 1000, 2)
            
            # 计算时间
            if 'moving_time' in segment:
                minutes, seconds = divmod(segment['moving_time'], 60)
                hours, minutes = divmod(minutes, 60)
                if hours > 0:
                    segment['formatted_time'] = f"{hours}时{minutes}分{seconds}秒"
                else:
                    segment['formatted_time'] = f"{minutes}分{seconds}秒"
            
            # 处理海拔变化
            if 'total_elevation_gain' in segment:
                segment['elevation_gain'] = round(segment['total_elevation_gain'], 1)
    
    # 解码路线数据
    points = decode_polyline(activity.get('map', {}).get('summary_polyline', ''))
    bounds = get_bounds(points) if points else None
    
    # 获取起点坐标
    start_latlng = activity.get('start_latlng', [])
    if start_latlng:
        start_lat = start_latlng[0]
        start_lng = start_latlng[1]
    else:
        start_lat = None
        start_lng = None
    
    return render_template('activity_detail.html', 
                         activity=activity,
                         points=points,
                         bounds=bounds,
                         start_lat=start_lat,
                         start_lng=start_lng,
                         segments=segments,
                         streams=stream_data if streams else None)

@app.route('/logout')
def logout():
    # 清除session中的令牌信息
    session.pop('access_token', None)
    session.pop('refresh_token', None)
    session.pop('expires_at', None)
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
    """获取数据的最大最小值，忽略None值
    
    Args:
        data: 数据列表
        
    Returns:
        (min_value, max_value) 元组
    """
    valid_data = [x for x in data if x is not None]
    if not valid_data:
        return None, None
    return min(valid_data), max(valid_data)

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
        
        return jsonify({
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
        })
    
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
        
        return jsonify({
            'status': 'success',
            'data': historical_weather
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

if __name__ == '__main__':
    # 确保templates目录存在
    if not os.path.exists('templates'):
        os.makedirs('templates')
    app.run(debug=True) 