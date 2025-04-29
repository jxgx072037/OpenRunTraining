import os
import requests
import json
import asyncio
import aiohttp
import re
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class AIService:
    def __init__(self):
        self.api_key = os.getenv('DEEPSEEK_API_KEY')
        self.base_url = "https://api.deepseek.com/v1"
        
        if not self.api_key:
            raise ValueError("DeepSeek API密钥未设置。请在.env文件中添加DEEPSEEK_API_KEY。")
        
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # 系统角色设定
        self.system_prompt = """
        # 设定
        你是一位专业的跑步训练顾问和教练，具有丰富的长跑、越野跑和山地跑经验。你精通运动生理学、训练计划制定和比赛策略分析。
        请基于提供的比赛路线数据分析，给出专业、细致且针对性的训练建议。
        1. 先分析赛道数据特征，主要关注每个赛段的爬升、下降以及坡度；
        2. 根据赛道数据特征，给出训练建议。训练地形要和赛道数据特征匹配。
        3. 输出的建议要简洁，不要超过200字。

        ## 原则
        1. 在最接近比赛日时训练特殊性最显著的生理机能，远离比赛日时训练一般性的生理机能；
        - 在长距离越野跑中，最一般性的生理机能是最大摄氧量强度。
        2. 在赛季过程中的某个时期，加入三个关键的训练：匀速跑、节奏跑和间歇跑；
        - 在长距离越野跑中，最合适的比赛强度是匀速跑和耐力跑，最不适合的比赛强度是最大摄氧量强度。
        3. 以8周（2个月）为一个训练模块，一次针对一种强度。如果凑不齐8周，可以适当调整。
        
        ## 其他注意事项：
        1. 考虑到大部分跑友只有能统计心率和GPX功能的手表和普通山地训练环境，不要推荐太复杂的训练设备，比如低压、高温训练舱等；

        ## 格式要求
        你生成的长期计划，应该遵循markdown的表格格式，比如（请参考以下格式，内容根据实际情况填写）：

        | 月份 | 训练类型 | 阶段目标 | 注释 |
        |:----:|:--------:|:--------:|:-----------------------------:|
        | 1月  | 间歇跑   | 提高最大摄氧量 | 低训练量、高强度 |
        | 2月  | 间歇跑   | 提高最大摄氧量 | 低训练量、高强度 |
        | 3月  | 节奏跑、乳酸阈值跑、长距离跑   | 乳酸门槛 | 最难的阶段，训练量大 |
        | 4月  | 最大化长距离跑 回归长距离跑 60分钟匀速跑  | 耐力 | 最大训练量，最低强度 |
        | x月 | ...   | ... | ... |
        | x月（比赛月）  | 最大化长距离跑 回归长距离跑 60分钟匀速跑 | 耐力 | 最大训练量，最低强度 |

        """
    
    async def generate_training_advice_stream(self, gpx_data, weather_data, match_date):
        """
        根据GPX和天气数据生成训练建议，使用流式响应
        """
        # 准备路线数据
        total_distance = gpx_data['stats']['distance']
        elevation_gain = gpx_data['stats']['elevation_gain']
        elevation_loss = gpx_data['stats']['elevation_loss']
        
        # 计算平均坡度
        if total_distance > 0:
            avg_grade = (elevation_gain / (total_distance * 1000)) * 100
        else:
            avg_grade = 0
            
        # 计算每公里爬升下降
        km_segments = []
        distances = gpx_data['elevation_data']['distances']
        elevations = gpx_data['elevation_data']['elevations']
        
        if len(distances) > 0 and len(elevations) > 0:
            curr_km = 1
            last_elevation = elevations[0]
            last_dist = 0
            km_gain = 0
            km_loss = 0
            
            for i in range(1, len(distances)):
                dist = distances[i]
                elev = elevations[i]
                
                # 计算高度差
                elev_diff = elev - last_elevation
                if elev_diff > 0:
                    km_gain += elev_diff
                else:
                    km_loss += abs(elev_diff)
                    
                # 如果超过了当前公里，记录数据
                if int(dist) > curr_km:
                    # 计算该公里的平均坡度
                    km_dist = dist - last_dist
                    if km_dist > 0:
                        km_grade = (km_gain / (km_dist * 1000)) * 100
                    else:
                        km_grade = 0
                        
                    # 添加到公里数据
                    km_segments.append({
                        'km': curr_km,
                        'gain': round(km_gain, 1),
                        'loss': round(km_loss, 1),
                        'grade': round(km_grade, 1)
                    })
                    
                    # 重置数据
                    curr_km = int(dist) + 1
                    last_dist = dist
                    km_gain = 0
                    km_loss = 0
                
                last_elevation = elev
        
        # 准备天气数据摘要
        weather_summary = "无天气数据"
        if weather_data and len(weather_data) > 0:
            latest_weather = weather_data[-1]  # 最近一年的天气数据
            weather_summary = f"温度: {latest_weather.get('temperature')}°C, 湿度: {latest_weather.get('humidity')}%, 降水: {latest_weather.get('precipitation')}mm, 风速: {latest_weather.get('windspeed')}km/h"
        
        # 构建公里分段数据文本
        km_data_text = ""
        if km_segments:
            km_data_text = "\n\n### 公里分段数据:\n"
            for seg in km_segments[:15]:  # 限制最多15个公里的数据，避免提示词过长
                km_data_text += f"- 第{seg['km']}公里: 爬升{seg['gain']}米, 下降{seg['loss']}米, 平均坡度{seg['grade']}%\n"
            
            if len(km_segments) > 15:
                km_data_text += f"- ...(共{len(km_segments)}公里)\n"

        import datetime
        time_now = datetime.datetime.now()
        time_now_str = time_now.strftime("%Y-%m-%d")
        
        # 构建提示信息
        prompt = f"""
        根据以下比赛路线和天气数据，提供详细的训练建议。

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
        
        # 构建API请求
        payload = {
            "model": "deepseek-reasoner",
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt}
            ],
            "stream": True,
            "max_tokens": 4096  # 最大token数
        }
        
        # 用于处理思考内容和最终回答
        reasoning_content = ""
        content = ""
        reasoning_content_end_flag = False
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"DeepSeek API错误: {response.status} - {error_text}")
                
                # 先输出<think>标签
                yield "<think>"
                
                # 处理流式响应
                async for line in response.content:
                    try:
                        line = line.decode('utf-8').strip()
                        if line == "data: [DONE]":
                            break
                        if line.startswith('data: '):
                            data = line[6:].strip()
                            delta = json.loads(data)['choices'][0]['delta']
                            content = delta.get('content')
                            reasoning_content = delta.get('reasoning_content')
                            
                            # 输出推理内容
                            if reasoning_content:
                                yield reasoning_content
                            # 输出正文内容
                            elif content:
                                # 如果是第一次收到正文内容
                                if not reasoning_content_end_flag:
                                    yield "\n</think>\n"
                                    reasoning_content_end_flag = True
                                yield content
                    except Exception as e:
                        print(f"错误处理流式响应: {e}")
                        continue
                        
# 单例模式
ai_service = AIService()

# 单元测试代码
async def run_test():
    """单元测试函数，用于测试API调用"""
    # 模拟GPX数据
    gpx_data = {
        'stats': {
            'distance': 100.0,  # 100公里
            'elevation_gain': 5000,  # 5000米爬升
            'elevation_loss': 4800  # 4800米下降
        },
        'elevation_data': {
            'distances': [0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0],
            'elevations': [200, 700, 1200, 1800, 2500, 3000, 3600, 4200, 3800, 2500, 400]
        }
    }
    
    # 模拟天气数据
    weather_data = [
        {
            'temperature': 25.6,
            'humidity': 65,
            'precipitation': 0.0,
            'windspeed': 12.4
        }
    ]

    match_date = "2026-01-18"
    
    print("正在测试...\n")
    content = ""
    async for chunk in ai_service.generate_training_advice_stream(gpx_data, weather_data, match_date):
        content += chunk
        print(chunk, end='', flush=True)

    # 保存到文件
    filename = "training_advice.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    
    print(f"训练建议已保存到 {filename}")
    return filename

    

# 如果直接运行此文件，则执行测试
if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    asyncio.run(run_test()) 